#!/usr/bin/env python
# -*- coding: utf-8 -*-
# File: mnist_center.py
# Author: Qian Ge <geqian1001@gmail.com>

import sys
import numpy as np
import tensorflow as tf
import platform
import scipy.misc
import argparse

sys.path.append('../')
from lib.dataflow.mnist import MNISTData 
from lib.model.ram import RAMClassification
from lib.helper.trainer import Trainer

if platform.node() == 'Qians-MacBook-Pro.local':
    DATA_PATH = '/Users/gq/Google Drive/Foram/CNN Data/code/GAN/MNIST_data/'
    SAVE_PATH = '/Users/gq/tmp/ram/center/'
    RESULT_PATH = '/Users/gq/tmp/ram/center/result/'
elif platform.node() == 'arostitan':
    DATA_PATH = '/home/qge2/workspace/data/MNIST_data/'
    SAVE_PATH = '/home/qge2/workspace/data/out/ram/'
else:
    DATA_PATH = 'E://Dataset//MNIST//'
    SAVE_PATH = 'E:/tmp/tmp/'

# BATCH_SIZE = 64 
# N_STEP = 3
# N_SAMPLE = 10
# GLIMPSE_SIZE = 12.0

def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--predict', action='store_true',
                        help='Run prediction')
    parser.add_argument('--train', action='store_true',
                        help='Train the model')
    parser.add_argument('--test', action='store_true',
                        help='Test')
    parser.add_argument('--trans', action='store_true',
                        help='Transform image')

    parser.add_argument('--step', type=int, default=1,
                        help='Number of glimpse')
    parser.add_argument('--sample', type=int, default=1,
                        help='Number of location samples during training')
    parser.add_argument('--glimpse', type=int, default=12,
                        help='Glimpse base size')
    parser.add_argument('--batch', type=int, default=128,
                        help='Batch size')
    parser.add_argument('--epoch', type=int, default=100,
                        help='Max number of epoch')
    
    return parser.parse_args()

class config_center():
    step = 6
    sample = 1
    glimpse = 8
    n_scales = 1
    batch = 128
    epoch = 1000
    loc_std = 0.11
    unit_pixel = 12

class config_transform():
    step = 6
    sample = 2
    glimpse = 12
    n_scales = 3
    batch = 128
    epoch = 2700
    loc_std = 0.22
    unit_pixel = 26

if __name__ == '__main__':
    FLAGS = get_args()
    if FLAGS.trans:
        name = 'trans'
        config = config_transform()
    else:
        name = 'centered'
        config = config_center()

    train_data = MNISTData('train', data_dir=DATA_PATH, shuffle=True)
    train_data.setup(epoch_val=0, batch_size=config.batch)
    valid_data = MNISTData('val', data_dir=DATA_PATH, shuffle=True)
    valid_data.setup(epoch_val=0, batch_size=10)

    model = RAMClassification(
                              im_channel=1,
                              glimpse_base_size=config.glimpse,
                              n_glimpse_scale=config.n_scales,
                              n_loc_sample=config.sample,
                              n_step=config.step,
                              n_class=10,
                              max_grad_norm=5.0,
                              unit_pixel=config.unit_pixel,
                              loc_std=config.loc_std,
                              is_transform=FLAGS.trans)
    model.create_model()

    trainer = Trainer(model, train_data)
    writer = tf.summary.FileWriter(SAVE_PATH)
    saver = tf.train.Saver()

    # gpu_options = tf.GPUOptions(per_process_gpu_memory_fraction=0.333)
    sessconfig = tf.ConfigProto()
    sessconfig.gpu_options.allow_growth = True
    with tf.Session(config=sessconfig) as sess:
        sess.run(tf.global_variables_initializer())
        if FLAGS.train:
            writer.add_graph(sess.graph)
            for step in range(0, config.epoch):
                trainer.train_epoch(sess, summary_writer=None)
                trainer.valid_epoch(sess, valid_data, config.batch)
                saver.save(sess, '{}ram-{}-mnist-step-{}'.format(SAVE_PATH, name, config.step), global_step=step)
        if FLAGS.predict:
            valid_data.setup(epoch_val=0, batch_size=30)
            saver.restore(sess, '{}ram-centered-mnist-step-6-999'.format(SAVE_PATH))
            
            batch_data = valid_data.next_batch_dict()
            trainer.test_batch(
                sess,
                batch_data,
                unit_pixel=config.unit_pixel,
                size=config.glimpse,
                scale=config.n_scales,
                save_path=RESULT_PATH)

        if FLAGS.test:
            train_data.setup(epoch_val=0, batch_size=2)
            batch_data = train_data.next_batch_dict()
            test, trans_im = sess.run(
                [model.layers['retina_reprsent'], model.pad_im],
                feed_dict={model.image: batch_data['data'],
                           model.label: batch_data['label'],
                           })
            # print(test.shape)
            tt = 0
            for glimpse_i, trans, im in zip(test, trans_im, batch_data['data']):
                scipy.misc.imsave('{}trans_{}.png'.format(SAVE_PATH, tt),
                                  np.squeeze(trans))
                for idx in range(0, 3):
                    scipy.misc.imsave('{}g_{}_{}.png'.format(SAVE_PATH, tt, idx), 
                                      np.squeeze(glimpse_i[0,:,:,idx]))
                scipy.misc.imsave('{}im_{}.png'.format(SAVE_PATH, tt), np.squeeze(im))
                tt += 1
        

        # writer.close()
