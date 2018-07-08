#!/usr/bin/env python
# -*- coding: utf-8 -*-
# File: mnist.py
# Author: Qian Ge <geqian1001@gmail.com>

import os
import numpy as np 
from tensorflow.examples.tutorials.mnist import input_data
from tensorcv.dataflow.base import RNGDataFlow

def identity(im):
    return im

def concat_pair(im_1, im_2):
    im_1 = np.expand_dims(im_1, axis=-1)
    im_2 = np.expand_dims(im_2, axis=-1)
    return np.concatenate((im_1, im_2), axis=-1)

def get_mnist_im_label(name, mnist_data):
    if name == 'train':
        return mnist_data.train.images, mnist_data.train.labels
    elif name == 'val':
        return mnist_data.validation.images, mnist_data.validation.labels
    else:
        return mnist_data.test.images, mnist_data.test.labels

class MNISTData(RNGDataFlow):
    def __init__(self, name, batch_dict_name=None, data_dir='', shuffle=True, pf=identity):
        assert os.path.isdir(data_dir)
        self._data_dir = data_dir

        self._shuffle = shuffle
        if pf is None:
            pf = identity
        self._pf = pf

        if not isinstance(batch_dict_name, list):
            batch_dict_name = [batch_dict_name]
        self._batch_dict_name = batch_dict_name

        assert name in ['train', 'test', 'val']
        self.setup(epoch_val=0, batch_size=1)

        self._load_files(name)
        self._image_id = 0

    def next_batch_dict(self):
        batch_data = self.next_batch()
        data_dict = {key: data for key, data in zip(self._batch_dict_name, batch_data)}
        return data_dict

    def _load_files(self, name):
        mnist_data = input_data.read_data_sets(self._data_dir, one_hot=False)
        self.im_list = []
        self.label_list = []

        mnist_images, mnist_labels = get_mnist_im_label(name, mnist_data)
        for image, label in zip(mnist_images, mnist_labels):
            # TODO to be modified
            image = np.reshape(image, [28, 28, 1])
            
            # image = np.reshape(image, [28, 28, 1])
            
            self.im_list.append(image)
            self.label_list.append(label)
        self.im_list = np.array(self.im_list)
        self.label_list = np.array(self.label_list)

        self._suffle_files()

    def _suffle_files(self):
        if self._shuffle:
            idxs = np.arange(self.im_list.shape[0])

            self.rng.shuffle(idxs)
            self.im_list = self.im_list[idxs]
            self.label_list = self.label_list[idxs]

    def size(self):
        return self.im_list.shape[0]

    def next_batch(self):
        assert self._batch_size <= self.size(), \
          "batch_size {} cannot be larger than data size {}".\
           format(self._batch_size, self.size())
        start = self._image_id
        self._image_id += self._batch_size
        end = self._image_id
        batch_files = []
        for im in self.im_list[start:end]:
            im = np.reshape(im, [28, 28])
            im = self._pf(im)
            im = np.expand_dims(im, axis=-1)
            batch_files.append(im)

        batch_label = self.label_list[start:end]

        if self._image_id + self._batch_size > self.size():
            self._epochs_completed += 1
            self._image_id = 0
            self._suffle_files()
        return [batch_files, batch_label]


class MNISTPair(MNISTData):
    def __init__(self,
                 name,
                 label_dict,
                 batch_dict_name=None,
                 data_dir='',
                 shuffle=True,
                 pf=identity,
                 pairprocess=concat_pair,
                 ):
        self._pair_fnc = pairprocess
        self._label_dict = label_dict
        super(MNISTPair, self).__init__(name=name,
                                        batch_dict_name=batch_dict_name,
                                        data_dir=data_dir,
                                        shuffle=shuffle,
                                        pf=pf,)

    def size(self):
        return int(np.floor(self.im_list.shape[0] / 2.0))

    def next_batch(self):
        assert self._batch_size <= self.size(), \
          "batch_size {} cannot be larger than data size {}".\
           format(self._batch_size, self.size())
        # start = self._image_id
        # self._image_id += self._batch_size * 2
        # end = self._image_id
        batch_files = []
        batch_label = []
        start = self._image_id
        for data_id in range(0, self._batch_size):
            im_1 = np.reshape(self.im_list[start], [28, 28])
            im_2 = np.reshape(self.im_list[start + 1], [28, 28])
            im = self._pair_fnc(im_1, im_2)
            im = np.expand_dims(im, axis=-1)
            batch_files.append(im)

            label_1 = self.label_list[start]
            label_2 = self.label_list[start + 1]
            label = self._label_dict['{}{}'.format(label_1, label_2)]
            batch_label.append(label)
            start = start + 2
        end = start
        self._image_id = end

        if self._image_id + self._batch_size > self.size():
            self._epochs_completed += 1
            self._image_id = 0
            self._suffle_files()
        return [batch_files, batch_label]

