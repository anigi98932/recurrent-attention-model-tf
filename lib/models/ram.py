#!/usr/bin/env python
# -*- coding: utf-8 -*-
# File: ram.py
# Author: Qian Ge <geqian1001@gmail.com>

import tensorflow as tf
from tensorcv.models.base import BaseModel
import tensorcv.models.layers as layers

from lib.utils.utils import get_shape2D
from lib.utils.tfutils import sample_normal_single
import lib.models.layers as L


class RAMClassification(BaseModel):
    def __init__(self,
                 im_size,
                 im_channel,
                 glimpse_base_size,
                 n_glimpse_scale,
                 n_loc_sample,
                 n_step,
                 n_class,
                 max_grad_norm,
                 loc_std,
                 unit_pixel,
                 transform_size=60):

        self._im_size = layers.get_shape2D(im_size)
        self._trans_size = transform_size
        self._n_channel = im_channel
        self._g_size = glimpse_base_size
        self._g_n = n_glimpse_scale
        self._n_l_sample = n_loc_sample
        self._l_std = loc_std
        self._unit_pixel = unit_pixel
        self._n_step = n_step
        self._n_class = n_class
        self._max_grad_norm = max_grad_norm

        self.layers = {}

    def create_model(self):
        self.set_is_training(True)
        self._create_input()
        with tf.variable_scope('core_net', reuse=tf.AUTO_REUSE):
            self.core_net(self.image)

    def _create_input(self):
        self.lr = tf.placeholder(tf.float32, name='lr')
        self.label = tf.placeholder(tf.int64, [None], name='label')
        self.image = tf.placeholder(tf.float32,
                                    [None, None, None, self._n_channel],
                                    name='image')

    def create_test_model(self):
        self.set_is_training(False)
        self._create_test_input()
        with tf.variable_scope('core_net', reuse=tf.AUTO_REUSE):
            self.core_net(self.test_image)

    def _create_test_input(self):
        self.label = tf.placeholder(tf.int64, [None], name='label')
        self.test_image = tf.placeholder(tf.float32,
                                         [None, None, None, self._n_channel],
                                         name='test_image')

    def core_net(self, inputs):
        self.layers['loc_mean'] = []
        self.layers['loc_sample'] = []
        self.layers['rnn_outputs'] = []
        self.layers['retina_reprsent'] = []

        inputs_im = inputs
        cell_size = 256
        batch_size = tf.shape(inputs_im)[0]

        init_loc_mean = tf.ones((batch_size, 2))
        loc_sample = tf.random_uniform((batch_size, 2), minval=-1, maxval=1)
        glimpse_out = self.glimpse_net(inputs_im, loc_sample)

        if self.is_training:
            inputs_im = tf.tile(inputs_im, [self._n_l_sample, 1, 1, 1])
            glimpse_out = tf.tile(glimpse_out, [self._n_l_sample, 1])
            batch_size = tf.shape(glimpse_out)[0]
            init_loc_mean = tf.tile(init_loc_mean, [self._n_l_sample, 1])
            loc_sample = tf.tile(loc_sample, [self._n_l_sample, 1])

        self.layers['loc_mean'].append(init_loc_mean)
        self.layers['loc_sample'].append(loc_sample)

        # RNN of core net
        h_prev = tf.zeros((batch_size, cell_size))
        for step_id in range(0, self._n_step):
            with tf.variable_scope('step', reuse=tf.AUTO_REUSE):
                lh = L.linear(out_dim=cell_size, inputs=h_prev, name='lh')
                lg = L.linear(out_dim=cell_size, inputs=glimpse_out, name='lg')
                h = tf.nn.relu(lh + lg, name='h')

            # core net does not trained through locatiion net
            loc_mean = self.location_net(tf.stop_gradient(h))
            if self.is_training:
                loc_sample = tf.stop_gradient(
                    sample_normal_single(loc_mean, stddev=self._l_std))
            else:
                loc_sample = loc_mean
                # loc_sample = tf.stop_gradient(
                #     sample_normal_single(loc_mean, stddev=self._l_std))

            glimpse_out = self.glimpse_net(inputs_im, loc_sample)
            action = self.action_net(h)

            # do not restore the last step location
            if step_id < self._n_step - 1:
                self.layers['loc_mean'].append(loc_mean)
                self.layers['loc_sample'].append(loc_sample)
            self.layers['rnn_outputs'].append(h)

            h_prev = h

        self.layers['class_logists'] = action
        self.layers['prob'] = tf.nn.softmax(logits=action, name='prob')
        self.layers['pred'] = tf.argmax(action, axis=1)    

    def get_accuracy(self):
        label = self.label
        if self.is_training:
                label = tf.tile(label, [self._n_l_sample])
        pred = self.layers['pred']
        accuracy = tf.reduce_mean(tf.cast(tf.equal(pred, label), tf.float32))
        return accuracy

    def get_train_op(self):
        self.cur_lr = self.lr

        loss = self.get_loss()
        var_list = tf.trainable_variables()
        grads = tf.gradients(loss, var_list)
        [tf.summary.histogram('gradient/' + var.name, grad, 
         collections = [tf.GraphKeys.SUMMARIES])
         for grad, var in zip(grads, var_list)]
        grads, _ = tf.clip_by_global_norm(grads, self._max_grad_norm)
        opt = tf.train.AdamOptimizer(self.cur_lr)
        train_op = opt.apply_gradients(zip(grads, var_list))
        return train_op

    def get_summary(self):
        return tf.summary.merge_all() 

    def glimpse_net(self, inputs, l_sample):
        """
            Args:
                inputs: [batch, h, w, c]
                l_sample: [batch, 2]
        """
        with tf.name_scope('glimpse_sensor'):
            max_r = int(self._g_size * (2 ** (self._g_n - 2)))
            inputs_pad = tf.pad(
                inputs,
                [[0, 0], [max_r, max_r], [max_r, max_r], [0, 0]],
                'CONSTANT') 

            #TODO use clipped location to compute prob or not?
            l_sample = tf.clip_by_value(l_sample, -1.0, 1.0)
            l_sample_adj = l_sample * 1.0 * self._unit_pixel / (self._im_size[0] / 2 + max_r)
            
            retina_reprsent = []
            for g_id in range(0, self._g_n):
                cur_size = self._g_size * (2 ** g_id)
                cur_glimpse = tf.image.extract_glimpse(
                    inputs_pad,
                    size=[cur_size, cur_size],
                    offsets=l_sample_adj,
                    centered=True,
                    normalized=True,
                    uniform_noise=True,
                    name='glimpse_sensor',
                    )
                cur_glimpse = tf.image.resize_images(
                    cur_glimpse,
                    size=[self._g_size, self._g_size],
                    method=tf.image.ResizeMethod.BILINEAR,
                    align_corners=False,
                    )
                retina_reprsent.append(cur_glimpse)
            retina_reprsent = tf.concat(retina_reprsent, axis=-1)
            self.layers['retina_reprsent'].append(retina_reprsent)
            
        with tf.variable_scope('glimpse_net'):
            out_dim = 128
            hg = L.linear(out_dim=out_dim,
                          inputs=retina_reprsent,
                          name='hg',
                          nl=tf.nn.relu)
            hl = L.linear(out_dim=out_dim,
                          inputs=l_sample,
                          name='hl',
                          nl=tf.nn.relu)

            out_dim = 256
            g = tf.nn.relu(
                L.linear(out_dim, inputs=hl, name='lhg') 
                + L.linear(out_dim, inputs=hg, name='lhl'),
                name='g')
            return g

    def location_net(self, core_state):
        with tf.variable_scope('loc_net'):
            l_mean = L.linear(out_dim=2, inputs=core_state, name='l_mean')
            # l_mean = tf.tanh(l_mean)
            l_mean = tf.clip_by_value(l_mean, -1., 1.)
            return l_mean

    def action_net(self, core_state):
        with tf.variable_scope('act_net'):
            act = L.linear(out_dim=self._n_class, inputs=core_state, name='act')
            return act

    def get_loss(self):
        try:
            return self.loss
        except AttributeError:
            self.loss = self._get_loss()
            return self.loss

    def _get_loss(self):
        return self._cls_loss() + self._REINFORCE()

    def _cls_loss(self):
        with tf.name_scope('class_cross_entropy'):
            label = self.label
            if self.is_training:
                label = tf.tile(label, [self._n_l_sample])
            logits = self.layers['class_logists']
            cross_entropy = tf.nn.sparse_softmax_cross_entropy_with_logits(
                logits=logits, labels=label)
            cross_entropy = tf.reduce_mean(cross_entropy)
            return cross_entropy

    def _REINFORCE(self):
        with tf.name_scope('REINFORCE'):
            label = self.label
            if self.is_training:
                label = tf.tile(label, [self._n_l_sample])
            pred = self.layers['pred']
            reward = tf.stop_gradient(tf.cast(tf.equal(pred, label), tf.float32))
            reward = tf.tile(tf.expand_dims(reward, 1), [1, self._n_step - 1]) # [b_size, n_step]

            loc_mean = tf.stack(self.layers['loc_mean'][1:]) # [n_step, b_size, 2]
            loc_sample = tf.stack(self.layers['loc_sample'][1:]) # [n_step, b_size, 2]
            dist = tf.distributions.Normal(loc=loc_mean, scale=self._l_std)
            log_prob = dist.log_prob(loc_sample) # [n_step, b_size, 2]
            log_prob = tf.reduce_sum(log_prob, -1) # [n_step, b_size]
            log_prob = tf.transpose(log_prob) # [b_size, n_step]

            baselines = self._comp_baselines()
            b_mse = tf.losses.mean_squared_error(labels=reward,
                                                 predictions=baselines)
            low_var_reward = (reward - tf.stop_gradient(baselines))
            
            REINFORCE_reward = tf.reduce_mean(log_prob * low_var_reward)

            loss = -REINFORCE_reward + b_mse
            return loss

    def _comp_baselines(self):
        with tf.variable_scope('baseline'):
            # core net does not trained through baseline loss
            rnn_outputs = tf.stop_gradient(self.layers['rnn_outputs'])
            baselines = []
            for step_id in range(0, self._n_step-1):
                b = L.linear(out_dim=1,
                             inputs=rnn_outputs[step_id],
                             name='baseline')
                b = tf.squeeze(b, axis=-1)
                baselines.append(b)
            
            baselines = tf.stack(baselines) # [n_step, b_size]
            baselines = tf.transpose(baselines) # [b_size, n_step]
            return baselines
