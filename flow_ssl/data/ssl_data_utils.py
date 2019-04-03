"""
Functions to load data from folders and augment it.
Adapted from https://github.com/benathi/fastswa-semi-sup
"""

import itertools
import logging
import os.path
import torchvision
import torch

from PIL import Image
import numpy as np
from torch.utils.data.sampler import Sampler


LOG = logging.getLogger('main')
NO_LABEL = -1


def make_ssl_data_loaders(
        data_path,
		label_path,
        labeled_batch_size,
        unlabeled_batch_size,
        num_workers, 
        transform_train, 
        transform_test, 
        use_validation=True, 
        ):

    train_dir = os.path.join(data_path, "train")
    if use_validation:
        print("Using train + validation")
        test_dir = os.path.join(data_path, "val")
    else:
        test_dir = os.path.join(data_path, "test")
    train_set = torchvision.datasets.ImageFolder(train_dir, transform_train)
    test_set = torchvision.datasets.ImageFolder(test_dir, transform_test)

    with open(label_path) as f:
        labels = dict(line.split(' ') for line in f.read().splitlines())
    labeled_idxs, unlabeled_idxs, num_classes = relabel_dataset(train_set, labels)
    assert len(train_set.imgs) == len(labeled_idxs) + len(unlabeled_idxs)

    print("Num classes", num_classes)
    print("Labeled data: ", len(labeled_idxs))
    print("Unlabeled data:", len(unlabeled_idxs))

    batch_sampler = LabeledUnlabeledBatchSampler(
            labeled_idxs, unlabeled_idxs, labeled_batch_size, unlabeled_batch_size)

    train_loader = torch.utils.data.DataLoader(
            train_set,
            batch_sampler=batch_sampler,
            num_workers=num_workers,
            pin_memory=True)

    test_loader = torch.utils.data.DataLoader(
            test_set,
            batch_size=labeled_batch_size+unlabeled_batch_size,
            shuffle=False,
            num_workers=2*num_workers,  # Needs images twice as fast
            pin_memory=True,
            drop_last=False)

    return train_loader, test_loader, num_classes


#PAVEL: relabels the dataset using the labels file.
def relabel_dataset(dataset, labels):
    num_classes = 0
    unlabeled_idxs = []
    for idx in range(len(dataset.imgs)):
        path, _ = dataset.imgs[idx]
        filename = os.path.basename(path)
        if filename in labels:
            label_idx = dataset.class_to_idx[labels[filename]]
            if label_idx > num_classes:
                num_classes = label_idx
            dataset.imgs[idx] = path, label_idx
            del labels[filename]
        else:
            dataset.imgs[idx] = path, NO_LABEL
            unlabeled_idxs.append(idx)

    num_classes += 1

    if len(labels) != 0:
        message = "List of unlabeled contains {} unknown files: {}, ..."
        some_missing = ', '.join(list(labels.keys())[:5])
        raise LookupError(message.format(len(labels), some_missing))

    labeled_idxs = sorted(set(range(len(dataset.imgs))) - set(unlabeled_idxs))

    return labeled_idxs, unlabeled_idxs, num_classes


class LabeledUnlabeledBatchSampler(Sampler):
    """Minibatch index sampler for labeled and unlabeled indices. 

    An epoch is one pass through the labeled indices.
    """
    def __init__(
            self, 
            labeled_idx, 
            unlabeled_idx, 
            labeled_batch_size, 
            unlabeled_batch_size):

        self.labeled_idx = labeled_idx
        self.unlabeled_idx = unlabeled_idx
        self.unlabeled_batch_size = unlabeled_batch_size
        self.labeled_batch_size = labeled_batch_size

        assert len(self.labeled_idx) >= self.labeled_batch_size > 0
        assert len(self.unlabeled_idx) >= self.unlabeled_batch_size > 0

    @property
    def num_labeled(self):
        return len(self.labeled_idx)

    def __iter__(self):
        labeled_iter = iterate_once(self.labeled_idx)
        unlabeled_iter = iterate_eternally(self.unlabeled_idx)
        return (
            labeled_batch + unlabeled_batch
            for (labeled_batch, unlabeled_batch)
            in  zip(batch_iterator(labeled_iter, self.labeled_batch_size),
                    batch_iterator(unlabeled_iter, self.unlabeled_batch_size))
        )

    def __len__(self):
        return len(self.labeled_idx) // self.labeled_batch_size


def iterate_once(iterable):
    return np.random.permutation(iterable)


def iterate_eternally(indices):
    def infinite_shuffles():
        while True:
            yield np.random.permutation(indices)
    return itertools.chain.from_iterable(infinite_shuffles())


def batch_iterator(iterable, n):
    "Collect data into fixed-length chunks or blocks"
    args = [iter(iterable)] * n
    return zip(*args)


#class RandomTranslateWithReflect:
#    """Translate image randomly
#
#    Translate vertically and horizontally by n pixels where
#    n is integer drawn uniformly independently for each axis
#    from [-max_translation, max_translation].
#
#    Fill the uncovered blank area with reflect padding.
#    """
#
#    def __init__(self, max_translation):
#    def __call__(self, old_image):
#        xtranslation, ytranslation = np.random.randint(-self.max_translation,
#                                                       self.max_translation + 1,
#                                                       size=2)
#        xpad, ypad = abs(xtranslation), abs(ytranslation)
#        xsize, ysize = old_image.size
#
#        flipped_lr = old_image.transpose(Image.FLIP_LEFT_RIGHT)
#        flipped_tb = old_image.transpose(Image.FLIP_TOP_BOTTOM)
#        flipped_both = old_image.transpose(Image.ROTATE_180)
#
#        new_image = Image.new("RGB", (xsize + 2 * xpad, ysize + 2 * ypad))
#
#        new_image.paste(old_image, (xpad, ypad))
#
#        new_image.paste(flipped_lr, (xpad + xsize - 1, ypad))
#        new_image.paste(flipped_lr, (xpad - xsize + 1, ypad))
#
#        new_image.paste(flipped_tb, (xpad, ypad + ysize - 1))
#        new_image.paste(flipped_tb, (xpad, ypad - ysize + 1))
#
#        new_image.paste(flipped_both, (xpad - xsize + 1, ypad - ysize + 1))
#        new_image.paste(flipped_both, (xpad + xsize - 1, ypad - ysize + 1))
#        new_image.paste(flipped_both, (xpad - xsize + 1, ypad + ysize - 1))
#        new_image.paste(flipped_both, (xpad + xsize - 1, ypad + ysize - 1))
#
#        new_image = new_image.crop((xpad - xtranslation,
#                                    ypad - ytranslation,
#                                    xpad + xsize - xtranslation,
#                                    ypad + ysize - ytranslation))
#
#        return new_image
#
#
##PAVEL: two different transformations to use for consistency regularization. 
##PAVEL: will not use these for now
#class TransformTwice:
#    def __init__(self, transform):
#        self.transform = transform
#
#    def __call__(self, inp):
#        out1 = self.transform(inp)
#        out2 = self.transform(inp)
#        return out1, out2
