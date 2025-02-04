import os
import math
import numpy as np
import torch
from monai import transforms, data
from monai.data import load_decathlon_datalist

class Sampler(torch.utils.data.Sampler):
    def __init__(self, dataset, num_replicas=None, rank=None,
                 shuffle=True, make_even=True):
        if num_replicas is None:
            if not torch.distributed.is_available():
                raise RuntimeError("Requires distributed package to be available")
            num_replicas = torch.distributed.get_world_size()
        if rank is None:
            if not torch.distributed.is_available():
                raise RuntimeError("Requires distributed package to be available")
            rank = torch.distributed.get_rank()
        self.shuffle = shuffle
        self.make_even = make_even
        self.dataset = dataset
        self.num_replicas = num_replicas
        self.rank = rank
        self.epoch = 0
        self.num_samples = int(math.ceil(len(self.dataset) * 1.0 / self.num_replicas))
        self.total_size = self.num_samples * self.num_replicas
        indices = list(range(len(self.dataset)))
        self.valid_length = len(indices[self.rank:self.total_size:self.num_replicas])

    def __iter__(self):
        if self.shuffle:
            g = torch.Generator()
            g.manual_seed(self.epoch)
            indices = torch.randperm(len(self.dataset), generator=g).tolist()
        else:
            indices = list(range(len(self.dataset)))
        if self.make_even:
            if len(indices) < self.total_size:
                if self.total_size - len(indices) < len(indices):
                    indices += indices[:(self.total_size - len(indices))]
                else:
                    extra_ids = np.random.randint(low=0,high=len(indices), size=self.total_size - len(indices))
                    indices += [indices[ids] for ids in extra_ids]
            assert len(indices) == self.total_size
        indices = indices[self.rank:self.total_size:self.num_replicas]
        self.num_samples = len(indices)
        return iter(indices)

    def __len__(self):
        return self.num_samples

    def set_epoch(self, epoch):
        self.epoch = epoch

def get_loader(args):
    data_dir = args.data_dir
    datalist_json = args.json_list
    train_transform = transforms.Compose(
        [
            transforms.LoadImaged(keys=["image", "label"]),
            transforms.AddChanneld(keys=["image", "label"]),
            transforms.Orientationd(keys=["image", "label"],
                                    axcodes="RAS"),
            transforms.ToTensord(keys=["image", "label"]),
        ]
    )
    val_transform = transforms.Compose(
        [
            transforms.LoadImaged(keys=["image", "label"]),
            transforms.AddChanneld(keys=["image", "label"]),
            transforms.Orientationd(keys=["image", "label"],
                                    axcodes="RAS"),
            transforms.ToTensord(keys=["image", "label"]),
        ]
    )
    test_transform = transforms.Compose(
        [
            transforms.LoadImaged(keys=["image"]),
            transforms.AddChanneld(keys=["image"]),
            transforms.Orientationd(keys=["image"], axcodes="RAS"),
            transforms.ToTensord(keys=["image"]),
        ]
    )


    if args.test_mode:
        test_files = load_decathlon_datalist(datalist_json,
                                            True,
                                            "testing",
                                            base_dir=data_dir)
        #print(test_files)
        test_ds = data.Dataset(data=test_files, transform=test_transform)
        test_sampler = Sampler(test_ds, shuffle=False) if args.distributed else None
        test_loader = data.DataLoader(test_ds,
                                     batch_size=1,
                                     shuffle=False,
                                     num_workers=args.workers,
                                     sampler=test_sampler,
                                     pin_memory=True,
                                     persistent_workers=True)
        loader = test_loader
    else:
        datalist = load_decathlon_datalist(datalist_json,
                                           True,
                                           "training",
                                           base_dir=data_dir)

        if args.use_normal_dataset:
            train_ds = data.Dataset(data=datalist, transform=train_transform)
        else:
            train_ds = data.CacheDataset(
                data=datalist,
                transform=train_transform,
                cache_num=1,
                cache_rate=1.0,
                num_workers=args.workers,
            )

        train_sampler = Sampler(train_ds) if args.distributed else None
        
        train_loader = data.DataLoader(train_ds,
                                       batch_size=args.batch_size,
                                       shuffle=(train_sampler is None),
                                       num_workers=args.workers,
                                       sampler=train_sampler,
                                       pin_memory=True,
                                       persistent_workers=True)
        val_files = load_decathlon_datalist(datalist_json,
                                            True,
                                            "validation",
                                            base_dir=data_dir)
        val_ds = data.Dataset(data=val_files, transform=val_transform)
        val_sampler = Sampler(val_ds, shuffle=False) if args.distributed else None
        val_loader = data.DataLoader(val_ds,
                                     batch_size=1,
                                     shuffle=False,
                                     num_workers=args.workers,
                                     sampler=val_sampler,
                                     pin_memory=True,
                                     persistent_workers=True)
        loader = [train_loader, val_loader]

    return loader
