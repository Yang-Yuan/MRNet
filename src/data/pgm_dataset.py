import os
import random
import glob
import numpy as np
import skimage.transform
import skimage.io

import torch
from torch.utils.data import Dataset

import warnings


class ToTensor(object):
    def __call__(self, sample):
        to_tensor(sample)


def to_tensor(sample):
    return torch.tensor(sample, dtype=torch.float32)


class PGMDataset(Dataset):
    def __init__(self, root, cache_root, split=None, regime='neutral', image_size=80, transform=None,
                 use_cache=False, save_cache=False, in_memory=False, subset=None, flip=False, permute=False):
        self.root = root
        self.cache_root = cache_root if cache_root is not None else root
        self.split = split
        self.regime = regime
        print([self.split, self.regime])

        self.image_size = image_size
        self.transform = transform
        self.use_cache = use_cache
        self.save_cache = save_cache
        self.flip = flip
        self.permute = permute

        def _set_paths():
            if self.root is not None:
                if os.path.isdir(os.path.join(self.root, 'data')):
                    self.data_dir = os.path.join(self.root, 'data', self.regime)
                else:
                    self.data_dir = os.path.join(self.root, self.regime)
            else:
                self.data_dir = None
            if self.use_cache:
                self.cached_dir = os.path.join(self.cache_root, 'cache', self.regime,
                                               f'{self.split}_{self.image_size}')
        _set_paths()

        if subset is not None:
            position_file_names_place = os.path.join('files', 'pgm', f'{subset}_{split}.txt')
            assert os.path.isfile(position_file_names_place), f'Subset file {position_file_names_place} not found'
            with open(position_file_names_place, "r") as file:
                contents = file.read()
                self.file_names = contents.splitlines()

            self.file_names = [os.path.basename(f) for f in self.file_names]
        else:
            data_dir = self.data_dir if self.data_dir is not None else self.cached_dir

            self.file_names = [f for f in os.listdir(data_dir) if self.split in f]
            self.file_names.sort()

            # Sanity
            assert split != 'train' or len(self.file_names) == 1200000, f'Train length = {len(self.file_names)}'
            assert split != 'val' or len(self.file_names) == 20000, f'Validation length = {len(self.file_names)}'
            assert split != 'test' or len(self.file_names) == 200000, f'Test length = {len(self.file_names)}'

        print(f'Dataset {self.split} size {len(self.file_names)} ')

        self.memory = None
        if in_memory:
            self.load_memory()

    def load_memory(self):
        self.memory = [None] * len(self.file_names)
        from tqdm import tqdm
        for idx in tqdm(range(len(self.file_names)), 'Loading Memory'):
            image, data, _ = self.get_data(idx)
            d = {'target': data["target"],
                 'meta_target': data["meta_target"],
                 'relation_structure': data["relation_structure"],
                 'relation_structure_encoded': data["relation_structure_encoded"]
                 }
            self.memory[idx] = (image, d)
            del data

    def save_image(self, image, file):
        image = image.numpy()
        os.makedirs(os.path.dirname(file), exist_ok=True)
        image_file = os.path.splitext(file)[0] + '.png'
        skimage.io.imsave(image_file, image.reshape(self.image_size, self.image_size))

    def load_image(self, file):
        image_file = os.path.splitext(file)[0] + '.png'
        gen_image = skimage.io.imread(image_file).reshape(1, self.image_size, self.image_size)
        if self.transform:
            gen_image = self.transform(gen_image)
        gen_image = to_tensor(gen_image)
        return gen_image

    def load_cached_file(self, file):
        try:
            data = np.load(file)
            return data
        except:
            print(f'Error - Could not open existing file {file}')
            return None

    def save_cached_file(self, file, data):
        os.makedirs(os.path.dirname(file), exist_ok=True)
        np.savez_compressed(file, **data)

    def __len__(self):
        return len(self.file_names)

    def get_data(self, idx):
        data_file = self.file_names[idx]
        if self.memory is not None and self.memory[idx] is not None:
            resize_image, data = self.memory[idx]
            return resize_image, data, data_file
        else:
            no_cache = True
            # Try to load a cached file for faster fetching
            if self.use_cache:
                cached_path = os.path.join(self.cached_dir, data_file)
                if os.path.isfile(cached_path):
                    data = self.load_cached_file(cached_path)
                    if data is not None:
                        resize_image = data['image'].astype(np.uint8)
                        return resize_image, data, data_file

                if no_cache and not self.save_cache:
                    warnings.warn(f'Error - Expected to load cached data "{data_file}" but cache was not found')

            # Load original file otherwise
            data_path = os.path.join(self.data_dir, data_file)
            try:
                data = np.load(data_path)
            except:
                print(f"Cannot load file {data_file}")
                raise

            image = data["image"].reshape(16, 160, 160)
            if self.image_size != 160:
                resize_image = []
                for idx in range(0, 16):
                    resize_image.append(
                        skimage.transform.resize(image[idx, :, :], (self.image_size, self.image_size),
                                                 order=1, preserve_range=True, anti_aliasing=True))
                resize_image = np.stack(resize_image, axis=0).astype(np.uint8)
            else:
                resize_image = image.astype(np.uint8)

            # Optional: save a cached file for further use
            if self.use_cache and self.save_cache:
                os.makedirs(os.path.dirname(cached_path), exist_ok=True)
                d = {'image': resize_image,
                     'target': data["target"],
                     'meta_target': data["meta_target"],
                     'relation_structure': data["relation_structure"],
                     'relation_structure_encoded': data["relation_structure_encoded"]
                     }
                self.save_cached_file(cached_path, d)

        return resize_image, data, data_file

    def __getitem__(self, idx):
        resize_image, data, data_file = self.get_data(idx)

        # Get additional data
        target = data["target"]
        meta_target = data["meta_target"]
        structure_encoded = data["relation_structure_encoded"]
        del data

        if self.transform:
            resize_image = self.transform(resize_image)
        resize_image = to_tensor(resize_image)

        if self.flip:
            if random.random() > 0.5:
                resize_image[[0, 1, 2, 3, 4, 5, 6, 7]] = resize_image[[0, 3, 6, 1, 4, 7, 2, 5]]

        if self.permute:
            old_target_image = resize_image[8+target].clone()

            new_indices = np.random.permutation(8)
            new_target = np.array(new_indices[target]).astype(np.int64)
            resize_image[8+new_indices] = resize_image[8:]

            new_target_image = resize_image[8+target].clone()
            assert old_target_image.eq(new_target_image).all()
            del old_target_image, new_target_image

            target = new_target

        target = torch.tensor(target, dtype=torch.long)
        meta_target = torch.tensor(meta_target, dtype=torch.float32)
        structure_encoded = torch.tensor(structure_encoded, dtype=torch.float32)

        return resize_image, target, meta_target, structure_encoded, data_file
