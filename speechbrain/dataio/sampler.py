"""PyTorch compatible samplers.

These determine the order of iteration through a dataset.

Authors:
  * Aku Rouhe 2020
  * Samuele Cornell 2020
  * Ralf Leibold 2020
  * Andreas Nautsch 2021
"""
import torch
import logging
from operator import itemgetter
from torch.utils.data import (
    RandomSampler,
    WeightedRandomSampler,
    DistributedSampler,
    Sampler,
)
import numpy as np
from typing import List
from speechbrain.dataio.dataset import DynamicItemDataset

logger = logging.getLogger(__name__)


class ReproducibleRandomSampler(RandomSampler):
    """A modification of RandomSampler which always returns the same values.

    Also look at `torch.utils.data.RandomSampler`. This has mostly
    the same behaviour and arguments, except for adding 'seed' and 'epoch' and
    not supporting 'generator'.

    Note
    ----
    Call `set_epoch` before every epoch. Otherwise, the sampler will produce the
    same sequence of indices every epoch.

    Arguments
    ---------
    data_source : Dataset
        The data source to sample indices for.
    seed : int
        The base seed to use for the random number generator. It is recommended
        to use a value which has a good mix of 0 and 1 bits.
    epoch : int
        The epoch to start at.

    Example
    -------
    >>> import torch
    >>> from speechbrain.utils.checkpoints import Checkpointer
    >>> from speechbrain.dataio.dataloader import SaveableDataLoader
    >>> # An example "dataset"
    >>> dataset = torch.arange(10).unsqueeze(1)
    >>> # Create the random sampler:
    >>> sampler = ReproducibleRandomSampler(dataset)
    >>> dataloader = SaveableDataLoader(dataset, sampler = sampler,
    ...     num_workers = 3)
    >>> # Setup the checkpointer.
    >>> # Note that the sampler doesn't need to be saved itself.
    >>> tmpdir = getfixture('tmpdir')
    >>> checkpointer = Checkpointer(tmpdir, {"dataloader": dataloader})
    >>> # Iterate:
    >>> subset = []
    >>> for i, data_point in enumerate(dataloader):
    ...     # Say you save a checkpoint on the fourth batch:
    ...     if i == 3:
    ...         _ = checkpointer.save_checkpoint(end_of_epoch = False)
    ...     # So let's save the numbers you would get if you continue
    ...     if i >= 4:
    ...         subset.append(data_point.item())
    >>> # What if instead you had to restart the experiment?
    >>> new_sampler = ReproducibleRandomSampler(dataset)
    >>> new_dataloader = SaveableDataLoader(dataset, sampler = new_sampler,
    ...        num_workers = 3)
    >>> new_checkpointer = Checkpointer(tmpdir, {"dataloader": new_dataloader})
    >>> _ = new_checkpointer.recover_if_possible()
    >>> # You'll get the same random order again:
    >>> new_subset = [data_point.item() for data_point in new_dataloader]
    >>> assert subset == new_subset

    """

    def __init__(self, data_source, seed=563375142, epoch=0, **kwargs):
        if "generator" in kwargs:
            MSG = (
                "Cannot give a separate generator when using "
                + "ReproducibleRandomSampler"
            )
            raise ValueError(MSG)
        super().__init__(data_source, **kwargs)
        self.seed = int(seed)
        self.epoch = epoch
        self.generator = torch.Generator()

    def set_epoch(self, epoch):
        """
        You can also just access self.epoch, but we maintain this interface
        to mirror torch.utils.data.distributed.DistributedSampler
        """
        self.epoch = epoch

    def __iter__(self):
        self.generator.manual_seed(self.seed + self.epoch)
        return super().__iter__()


class ReproducibleWeightedRandomSampler(WeightedRandomSampler):
    """A reproducible modification of WeightedRandomSampler.

    Also look at `torch.utils.data.WeightedRandomSampler`. This has the
    the same behaviour and arguments, except for adding 'seed' and 'epoch' and
    not supporting 'generator'.

    Note
    ----
    Call `set_epoch` before every epoch. Otherwise, the sampler will produce the
    same sequence of indices every epoch.

    Arguments
    ---------
    weights : sequence of float
        Weights for each index. Doesn't need to sum to one.
    num_samples : int
        Number of samples to draw
    replacement : bool
        To draw with replacement or not (within an epoch of num_samples).
    seed : int
        The base seed to use for the random number generator. It is recommended
        to use a value which has a good mix of 0 and 1 bits.
    epoch : int
        The epoch to start at.

    Example
    -------
    >>> a = ReproducibleWeightedRandomSampler([0.1, 0.9, 0.4, 0.7, 3.0, 0.6], 5, replacement=True)
    >>> b = ReproducibleWeightedRandomSampler([0.1, 0.9, 0.4, 0.7, 3.0, 0.6], 5, replacement=True)
    >>> list(a)
    [3, 1, 4, 4, 4]
    >>> list(b)
    [3, 1, 4, 4, 4]
    >>> a.set_epoch(1)
    >>> list(a)
    [4, 5, 4, 4, 3]
    >>> b.set_epoch(1)
    >>> list(b)
    [4, 5, 4, 4, 3]


    """

    def __init__(
        self,
        weights,
        num_samples,
        replacement,
        seed=129491412,
        epoch=0,
        **kwargs,
    ):
        if "generator" in kwargs:
            MSG = (
                "Cannot give a separate generator when using "
                + "ReproducibleRandomSampler"
            )
            raise ValueError(MSG)
        super().__init__(weights, num_samples, replacement, **kwargs)
        self.seed = int(seed)
        self.epoch = epoch
        self.generator = torch.Generator()

    def set_epoch(self, epoch):
        """
        You can also just access self.epoch, but we maintain this interface
        to mirror torch.utils.data.distributed.DistributedSampler
        """
        self.epoch = epoch

    def __iter__(self):
        self.generator.manual_seed(self.seed + self.epoch)
        return super().__iter__()


class ConcatDatasetBatchSampler(Sampler):
    """This sampler is built to work with a standard Pytorch ConcatDataset.

    It is used to retrieve elements from the different concatenated datasets placing them in the same batch
    with proportion specified by batch_sizes, e.g 8, 16 means each batch will
    be of 24 elements with the first 8 belonging to the first dataset in ConcatDataset
    object and the last 16 to the second.
    More than two datasets are supported, in that case you need to provide 3 batch
    sizes.

    Note
    ----
    Batched are drawn from the datasets till the one with smallest length is exhausted.
    Thus number of examples in your training epoch is dictated by the dataset
    whose length is the smallest.


    Arguments
    ---------
    samplers : int
        The base seed to use for the random number generator. It is recommended
        to use a value which has a good mix of 0 and 1 bits.
    batch_sizes: list
        Batch sizes.
    epoch : int
        The epoch to start at.

    Example
    -------
    >>> import torch
    >>> from speechbrain.dataio.sampler import ConcatDatasetBatchSampler, ReproducibleRandomSampler
    >>> from speechbrain.dataio.sampler import ReproducibleRandomSampler
    >>> from speechbrain.dataio.dataloader import SaveableDataLoader
    >>> # example "datasets"
    >>> dataset1 = torch.arange(0, 10).unsqueeze(1)
    >>> dataset2 = torch.arange(20, 40).unsqueeze(1)
    >>> tot_dataset = torch.utils.data.ConcatDataset([dataset1, dataset2])
    >>> sampler1 = ReproducibleRandomSampler(dataset1)
    >>> sampler2 = ReproducibleRandomSampler(dataset2)
    >>> tot_sampler = ConcatDatasetBatchSampler([sampler1, sampler2], [2, 4])
    >>> dataloader = SaveableDataLoader(tot_dataset, batch_sampler = tot_sampler,
    ...     num_workers = 3)
    >>> for data_point in dataloader:
    ...      assert len(data_point) == 6
    ...      for i in range(2):
    ...         assert data_point[i] in [x for x in range(0, 10)]
    ...      for i in range(2, 4):
    ...         assert data_point[i] in [x for x in range(10, 40)]
    """

    def __init__(self, samplers, batch_sizes: (tuple, list), epoch=0) -> None:

        if not isinstance(samplers, (list, tuple)):
            raise ValueError(
                "samplers should be a list or tuple of Pytorch Samplers, "
                "but got samplers={}".format(batch_sizes)
            )

        if not isinstance(batch_sizes, (list, tuple)):
            raise ValueError(
                "batch_sizes should be a list or tuple of integers, "
                "but got batch_sizes={}".format(batch_sizes)
            )

        if not len(batch_sizes) == len(samplers):
            raise ValueError(
                "batch_sizes and samplers should be have same length"
            )

        self.batch_sizes = batch_sizes
        self.samplers = samplers
        self.offsets = [0] + np.cumsum(
            [len(x) for x in self.samplers]
        ).tolist()[:-1]

        self.epoch = epoch
        self.set_epoch(self.epoch)

    def _iter_one_dataset(self, c_batch_size, c_sampler, c_offset):
        batch = []
        for idx in c_sampler:
            batch.append(c_offset + idx)
            if len(batch) == c_batch_size:
                yield batch

    def set_epoch(self, epoch):
        """You can also just access self.epoch, but we maintain this interface
        to mirror ``torch.utils.data.distributed.DistributedSampler``.
        """
        if hasattr(self.samplers[0], "epoch"):
            for s in self.samplers:
                s.set_epoch(epoch)

    def __iter__(self):

        iterators = [iter(i) for i in self.samplers]
        tot_batch = []

        for b_num in range(len(self)):
            for samp_idx in range(len(self.samplers)):
                c_batch = []
                while len(c_batch) < self.batch_sizes[samp_idx]:
                    c_batch.append(
                        self.offsets[samp_idx] + next(iterators[samp_idx])
                    )
                tot_batch.extend(c_batch)
            yield tot_batch
            tot_batch = []

    def __len__(self):

        min_len = float("inf")
        for idx, sampler in enumerate(self.samplers):
            c_len = len(sampler) // self.batch_sizes[idx]
            min_len = min(c_len, min_len)

        return min_len


class DynamicBatchSampler(Sampler):
    """This BatchSampler batches examples together by grouping them by their length.

    Every example in the batch have approximately the same length and
    thus padding is minimized.
    This enables faster training on datasets
    where length of examples can vary significantly (e.g Librispeech).
    Inspired by: https://www.tensorflow.org/api_docs/python/tf/data/experimental/bucket_by_sequence_length

    Dynamic batching is performed by specifying a max_batch_length which is the
    upper limit for the sum of the length of examples in a batch:
    e.g., if ex1 has length 4, ex2 length 5 and if max_batch_length is set to 6
    ex1 and ex2 will be placed, alone, in two distinct batches.

    Length for each example can be obtained in two manners.
    If the input dataset is a DynamicItemDataset it can be obtained by specifying a
    length_func. Default assumes a "duration" entry is in the annotation.
    Length for each example can also be passed to this class upon instantiation
    by specifying a list containing the length for each example and passing it to
    lengths_list.

    Examples are grouped together by defining a set of possible discrete intervals
    (buckets) multiple of a left_bucket_length.
    A bucket_length_multiplier is used to specify the number of possible buckets.
    E.g., if max_batch_length = 32 and left_bucket_length = 10, bucket_length_multiplier = 2
    there will be 3 buckets: [0, 10), [10, 20), [20, 40).
    A common choice would be setting left_bucket_length to approximately the length
    of your shortest example in the dataset.
    Decreasing bucket_length_multiplier creates more buckets in the whole interval
    of [left_bucket_length, max_batch_size]: e.g. if max_batch_length = 32 and left_bucket_length = 10,
    bucket_length_multiplier = 1.5 the number of buckets increases to 8.
    With right boundaries: [10 12 14 17 21 25 30 36].
    Thus examples with length less than 10 are all grouped together but more buckets
    are created for longer examples.
    Note that the bucket boundary grows exponentially using the multiplier.

    The buckets can also be specified by passing a list to the bucket_boundaries
    argument instead of specifying a left_bucket_length and a bucket_length_multiplier.

    Example
    -------
    >>> import torch
    >>> import speechbrain as sb
    >>> from speechbrain.dataio.sampler import DynamicBatchSampler
    >>> from speechbrain.dataio.dataset import DynamicItemDataset
    >>> from speechbrain.dataio.dataloader import SaveableDataLoader
    >>> from speechbrain.dataio.batch import PaddedBatch
    >>> import numpy as np
    >>> item_lengths = sorted([np.random.randint(10, 100) for x in range(20)])
    >>> dataset = {"ex_{}".format(x) : {"wav" :torch.randn(x)} for x in item_lengths}
    >>> dataset = DynamicItemDataset(dataset)
    >>> dataset.set_output_keys(["wav"])
    >>> length_func = lambda x : len(x) # trivial in this example
    >>> bsampler = DynamicBatchSampler(dataset, 20, 10, 1.1, length_func, shuffle=False, batch_ordering='descending')
    >>> dataloader = SaveableDataLoader(dataset, batch_sampler=bsampler, collate_fn=PaddedBatch)
    >>> for i, b in enumerate(dataloader):
    ...     data, length = b["wav"]
    >>> assert data.shape[-1] == max(item_lengths)

    Arguments
    ---------
    dataset : torch.utils.data.Dataset
        Pytorch Dataset from which elements will be sampled.
    max_batch_length : int
        Upper limit for the sum of the length of examples in a batch.
        Should be chosen based on your GPU memory.
    left_bucket_length : int
        Minimum length of a bucket. Specifies resolution of buckets and thus this sampler
        stochasticity. A common choice is to set this to length of your
        shortest example.
    bucket_length_multiplier : float
        Multiplier for bucket length, specifies number of buckets from left_bucket_length to
        max_batch_length.
    length_func : callable
        Function used to get length of each example from the dataset.
        This argument can be used only when the dataset is a Speechbrain DynamicItemDataset object.
        Can be anything: e.g. lambda x: x["duration"]*16000 returns number of samples
        if duration key in the annotation is in seconds and the file has 16kHz sampling freq.
    shuffle : bool
        Whether or not shuffle examples between each epoch.
    batch_ordering : string
        If ``random``, batches are randomly permuted; otherwise ``ascending`` or ``descending`` sorted by length.
    bucket_boundaries : list
        Overrides bucket_length_multiplier and left_bucket_length by specifying manually
        the buckets right boundaries.
    lengths_list: list
        Overrides length_func by passing a list containing the length of each example
        in the dataset. This argument must be set when the dataset is a plain
        Pytorch Dataset object and not a DynamicItemDataset object as length_func
        cannot be used on Pytorch Datasets.
    epoch : int
        The epoch to start at.
    reduce_padding_afterwards : bool
        If ``True``, the sampler will randomly re-assign short(er) examples from
        buckets of highest padding among other buckets;
        until total remaining padding < max_batch_length.
    num_quantiles : int
        If set, the sampler will map the distribution density function to a standard lognormal pdf,
        create num_quantiles quantile bins there, and return the corresponding duration values.
        This overrides left_bucket_length and bucket_length_multiplier parameters.
    drop_last : bool
         If ``True``, the sampler will drop the last examples which
         have not been grouped.
    """

    def __init__(
        self,
        dataset,
        max_batch_length: int,
        left_bucket_length: int,
        bucket_length_multiplier: float = 1.1,
        length_func=lambda x: x["duration"],
        shuffle: bool = True,
        batch_ordering: str = "random",
        bucket_boundaries: List[int] = [],
        lengths_list: List[int] = None,
        seed: int = 42,
        epoch: int = 0,
        reduce_padding_afterwards: bool = False,
        num_quantiles: int = None,
        drop_last: bool = False,
    ):
        self._dataset = dataset
        self._ex_lengths = {}
        ex_ids = self._dataset.data_ids

        if lengths_list is not None:
            # take length of examples from this argument and bypass length_key
            for indx in range(len(lengths_list)):
                self._ex_lengths[str(indx)] = lengths_list[indx]
        else:
            # use length func
            if not isinstance(dataset, DynamicItemDataset):
                raise NotImplementedError(
                    "Dataset should be a Speechbrain DynamicItemDataset when using length function"
                )
            for indx in range(len(self._dataset)):
                self._ex_lengths[str(indx)] = length_func(
                    self._dataset.data[ex_ids[indx]]
                )

        if bucket_boundaries is not None:
            if not all([x >= 1 for x in bucket_boundaries]):
                raise ValueError(
                    "All elements in bucket boundaries should be >= 1."
                )
            if not len(set(bucket_boundaries)) == len(bucket_boundaries):
                raise ValueError(
                    "Bucket_boundaries should not contain duplicates."
                )

        if num_quantiles is not None:
            self._bucket_boundaries = np.array(
                self._get_boundaries_through_warping(
                    max_batch_length=max_batch_length,
                    bucket_boundaries=bucket_boundaries,
                    num_quantiles=num_quantiles,
                )
            )
        else:
            self._bucket_boundaries = np.array(
                self._get_data_boundaries(
                    max_batch_length=max_batch_length,
                    bucket_boundaries=bucket_boundaries,
                    left_bucket_length=left_bucket_length,
                    bucket_length_multiplier=bucket_length_multiplier,
                )
            )

        self._max_batch_length = max_batch_length
        self._shuffle_ex = shuffle
        self._batch_ordering = batch_ordering
        self._seed = seed
        self._reduce_padding_afterwards = reduce_padding_afterwards
        self._drop_last = drop_last
        # Calculate bucket lengths - how often does one bucket boundary fit into max_batch_length?
        self._bucket_lens = [
            max(1, int(max_batch_length / self._bucket_boundaries[i]))
            for i in range(len(self._bucket_boundaries))
        ] + [1]
        self._epoch = epoch
        self._generate_batches()

    def _get_data_boundaries(
        self,
        max_batch_length: int,
        bucket_boundaries: List[int],
        left_bucket_length: int,
        bucket_length_multiplier: float,
    ) -> List[int]:
        if not bucket_boundaries:
            if left_bucket_length <= 0:
                raise ValueError(
                    "left_bucket_length must be >0 if no bucket_boundaries set"
                )
            if bucket_length_multiplier < 1.0:
                raise ValueError(
                    "bucket_length_multiplier must be >1.0 if no bucket_boundaries set"
                )
            bucket_boundaries = {left_bucket_length}
            bucket_boundary = float(left_bucket_length)
            while True:
                bucket_boundary *= bucket_length_multiplier
                if bucket_boundary >= max_batch_length:
                    break
                bucket_boundaries.add(bucket_boundary)

        return list(sorted(bucket_boundaries))

    def get_durations(self, batch):
        return [self._ex_lengths[str(idx)] for idx in batch]

    def _get_boundaries_through_warping(
        self,
        max_batch_length: int,
        bucket_boundaries: List[int],
        num_quantiles: int,
    ) -> List[int]:
        # the following lines do not cover that there is only one example in the dataset
        if not bucket_boundaries:
            # warp frames (duration) distribution of train data
            logger.info("Batch quantisation in latent space")
            # linspace set-up
            num_boundaries = num_quantiles + 1
            # create latent linearly equal spaced buckets
            latent_boundaries = np.linspace(
                1 / num_boundaries,
                num_quantiles / num_boundaries,
                num_quantiles,
            )
            # use lognormal distribution
            from scipy.stats import lognorm

            # get quantiles
            quantiles = lognorm.ppf(latent_boundaries, 1)
            # scale up to to max_batch_length
            bucket_boundaries = quantiles * max_batch_length / quantiles[-1]
        # compute resulting bucket length multipliers
        length_multipliers = [
            bucket_boundaries[x + 1] / bucket_boundaries[x]
            for x in range(num_quantiles - 1)
        ]
        # logging
        logger.info(
            "Latent bucket boundary - buckets: {} - length multipliers: {}".format(
                list(map("{:.2f}".format, bucket_boundaries)),
                list(map("{:.2f}".format, length_multipliers)),
            )
        )
        return list(sorted(bucket_boundaries))

    def _permute_batches(self):

        if self._batch_ordering == "random":
            # deterministically shuffle based on epoch and seed
            g = torch.Generator()
            g.manual_seed(self._seed + self._epoch)
            sampler = torch.randperm(
                len(self._batches), generator=g
            ).tolist()  # type: ignore
            tmp = []
            for idx in sampler:
                tmp.append(self._batches[idx])
            self._batches = tmp

        elif self._batch_ordering == "ascending":
            self._batches = sorted(
                self._batches,
                key=lambda x: max([self._ex_lengths[str(idx)] for idx in x]),
            )
        elif self._batch_ordering == "descending":
            self._batches = sorted(
                self._batches,
                key=lambda x: max([self._ex_lengths[str(idx)] for idx in x]),
                reverse=True,
            )
        else:
            raise NotImplementedError

    def _reduce_padding(self):
        # copy for rolling back a re-assignment when batch size exceed maximum
        from copy import deepcopy

        # repeat twice - sometimes a fallback will cause non-depleted batches that could actually be depleted
        for cnt in range(2):
            # number of frames per batch
            batch_frames = [
                sum(self._ex_lengths[str(idx)] for idx in batch)
                for batch in self._batches
            ]
            # Remaining padding per batch
            remaining_padding = self._max_batch_length - np.asarray(
                batch_frames
            )
            # do not touch batches with too long samples (exponential memory usage) - 80% is arbitrary
            remaining_padding[
                np.asarray(batch_frames) > 0.8 * self._max_batch_length
            ] = 0
            # Find uncompleted buckets
            non_zero_buckets_in_sorted = np.in1d(
                np.argsort(batch_frames), np.where(batch_frames), 1
            )
            # Sort their IDs by unused padding
            unused_padding_sorted = np.argsort(batch_frames)[
                non_zero_buckets_in_sorted
            ]
            # Re-assign examples from remaining batches
            for batch_id in unused_padding_sorted:
                batch = self._batches[batch_id]
                # prepare fallback if batch cannot be depleted
                if batch:
                    # prepare 'call-by-value'
                    # create tmp objects to manipulate (play with)
                    tmp_remaining_padding = deepcopy(remaining_padding)
                    tmp_batches = deepcopy(self._batches)
                    # avoid that any other batch wants to put sth in this batch which is about to be depleted
                    remaining_padding[batch_id] = 0
                # re-assign each example in the uncompleted bucket batch
                for pos in reversed(range(len(batch))):
                    # pop first example in batch
                    idx = batch.pop(
                        pos
                    )  # 'pos' is necessary for potential later re-append
                    # length of pre-sampled audio
                    item_len = self._ex_lengths[str(idx)]
                    # where is enough padding
                    possible_batches = np.argwhere(
                        np.array(remaining_padding) >= item_len
                    )
                    if len(possible_batches) == 0:
                        # stop re-assign -OR- put back & move on
                        remaining_padding = deepcopy(tmp_remaining_padding)
                        self._batches = deepcopy(tmp_batches)
                        # next one
                        continue
                    else:
                        # random idx selection of where is enough padding; exclude self
                        rand_batch_idx = np.random.choice(
                            possible_batches.flatten()
                        )
                        # assign to batch
                        self._batches[rand_batch_idx].append(idx)
                        # keep track of durations
                        remaining_padding[rand_batch_idx] -= item_len
        # remove empty elements
        self._batches = [batch for batch in self._batches if batch]

    def _generate_batches(self):
        logger.info("DynamicBatchSampler: Generating dynamic batches")

        if self._shuffle_ex:
            # deterministically shuffle based on epoch and seed
            g = torch.Generator()
            g.manual_seed(self._seed + self._epoch)
            sampler = torch.randperm(len(self._dataset), generator=g).tolist()  # type: ignore
        else:
            # take examples as they are: e.g. they have been sorted
            sampler = range(len(self._dataset))  # type: ignore

        self._batches = []
        bucket_batches = [[] for i in self._bucket_lens]
        bucket_stats = [0 for i in self._bucket_lens]
        if self._reduce_padding_afterwards:
            bucket_frames = [0 for i in self._bucket_lens]
            batch_frames = []
        for idx in sampler:
            # length of pre-sampled audio
            item_len = self._ex_lengths[str(idx)]
            # bucket to fill up most padding
            bucket_id = np.searchsorted(self._bucket_boundaries, item_len)
            # fill audio's duration into that bucket
            bucket_batches[bucket_id].append(idx)
            # track #samples - why not duration/#frames; rounded up?
            bucket_stats[bucket_id] += 1
            # keep track of durations, if necessary
            if self._reduce_padding_afterwards:
                bucket_frames[bucket_id] += item_len
            # if full, put bucket to the end
            if len(bucket_batches[bucket_id]) >= self._bucket_lens[bucket_id]:
                self._batches.append(bucket_batches[bucket_id])
                bucket_batches[bucket_id] = []
                # keep track of durations
                if self._reduce_padding_afterwards:
                    batch_frames.append(bucket_frames[bucket_id])
                    bucket_frames[bucket_id] = 0

        # Dump remaining batches - yet, we might even want to shuffle those
        if not self._drop_last:
            for batch in bucket_batches:
                if batch:
                    self._batches.append(batch)

        # sort in remaining batches & re-assign badly filled buckets
        if self._reduce_padding_afterwards:
            self._reduce_padding()

        if not self._shuffle_ex:
            self._permute_batches()  # reorder batches

        if self._epoch == 0:  # only log at first epoch
            # frames per batch & their padding remaining
            batch_frames = [
                sum(self._ex_lengths[str(idx)] for idx in batch)
                for batch in self._batches
            ]
            remaining_padding = self._max_batch_length - np.asarray(
                batch_frames
            )
            # logging
            logger.info(
                (
                    "DynamicBatchSampler: Created {} batches, {} buckets used - with remaining frame paddings: "
                    + "min/µ/max ({:.2f}, {:.2f}, {:.2f}) and total/σ ({:.2f}, {:.2f})."
                ).format(
                    len(self._batches),
                    len(self._bucket_boundaries),
                    remaining_padding.min(),
                    remaining_padding.mean(),
                    remaining_padding.max(),
                    remaining_padding.sum(),
                    remaining_padding.std(),
                )
            )
            boundaries = [0] + self._bucket_boundaries.tolist()
            for i in range(len(self._bucket_boundaries)):
                logger.info(
                    (
                        "DynamicBatchSampler: Bucket {} with boundary {:.1f}-{:.1f} and "
                        + "batch_size {} has {} examples."
                    ).format(
                        i,
                        np.around(boundaries[i], 2),
                        np.around(boundaries[i + 1], 2),
                        self._bucket_lens[i],
                        bucket_stats[i],
                    )
                )
            padding_details = "Batch {} with {:.1f} frames in {} files - {:.1f} padding remains."
            if self._reduce_padding_afterwards:
                padding_details = "(post re-assigns) " + padding_details
            padding_details = "DynamicBatchSampler: " + padding_details
            for i in range(len(batch_frames)):
                logger.info(
                    padding_details.format(
                        i,
                        batch_frames[i],
                        len(self._batches[i]),
                        remaining_padding[i],
                    )
                )

    def __iter__(self):
        for batch in self._batches:
            yield batch
        if self._shuffle_ex:  # re-generate examples if ex_ordering == "random"
            self._generate_batches()
        elif self._shuffle_ex is False and self._batch_ordering == "random":
            # we randomly permute the batches only --> faster
            self._permute_batches()
        else:
            pass

    def set_epoch(self, epoch):
        """
        You can also just access self.epoch, but we maintain this interface
        to mirror torch.utils.data.distributed.DistributedSampler
        """
        self._epoch = epoch
        self._generate_batches()

    def __len__(self):
        return len(self._batches)


# Heavily inspired by Catalyst, which is under Apache 2.0 licence.
# https://github.com/catalyst-team/catalyst/blob/51428d7756e62b9b8ee5379f38e9fd576eeb36e5/catalyst/data/sampler.py#L522
class DistributedSamplerWrapper(DistributedSampler):
    """This wrapper allows using any sampler with Distributed Data Parallel (DDP) correctly.

    Passing blindly the sampler to each DDP process will cause to have access
    within each process to all the data in the dataset instead of only a subset
    of it which is unique to each process.  This wrapper prevents this and
    allows to use only a subset of the original data for each process.

    NOTE
    ----
    This is is automatically applied to any sampler in the Brain class when DDP
    training is used.
    """

    def __init__(self, sampler, *args, **kwargs):
        # DistributedSampler only calls len() on dataset
        # so a sampler is fine to pass there, as well.
        super().__init__(dataset=sampler, *args, **kwargs)
        self.sampler = sampler

    def __iter__(self):
        # It is easiest to use a random access interface to the wrapped
        # sampler's indices, so we just fetch all indices from the wrapped
        # sampler
        sampler_indices = list(self.sampler.__iter__())
        indices_of_indices = super().__iter__()
        # Itemgetter fetches the wrapped sampler indices from the positions
        # pointed to by DistributedSampler
        return iter(itemgetter(*indices_of_indices)(sampler_indices))

    def set_epoch(self, epoch):
        """Pass set_epoch() through to DistributedSampler and the wrapper one"""
        super().set_epoch(epoch)
        if hasattr(self.sampler, "set_epoch"):
            self.sampler.set_epoch(epoch)
