import torch
from typing import Tuple, Union


CropSize = Union[int, Tuple[int, int]]


def _parse_crop_size(crop_size: CropSize) -> Tuple[int, int]:
    if isinstance(crop_size, int):
        if crop_size <= 0:
            raise ValueError("crop_size must be > 0")
        return crop_size, crop_size
    if (
        isinstance(crop_size, tuple)
        and len(crop_size) == 2
        and all(isinstance(x, int) for x in crop_size)
    ):
        h, w = crop_size
        if h <= 0 or w <= 0:
            raise ValueError("crop_size values must be > 0")
        return h, w
    raise TypeError("crop_size must be an int or a tuple of two ints (h, w)")


def random_crop_chw(img: torch.Tensor, crop_size: CropSize) -> torch.Tensor:
    """
    Random crop for a single image tensor shaped (C, H, W).
    """
    if not isinstance(img, torch.Tensor):
        raise TypeError("img must be a torch.Tensor")
    if img.ndim != 3:
        raise ValueError(f"Expected img shape (C,H,W). Got {tuple(img.shape)}")

    c, H, W = img.shape
    h, w = _parse_crop_size(crop_size)

    if h > H or w > W:
        raise ValueError(f"Crop {(h, w)} larger than image {(H, W)}")

    top = torch.randint(0, H - h + 1, (1,)).item()
    left = torch.randint(0, W - w + 1, (1,)).item()

    return img[:, top:top + h, left:left + w]


def random_crop_bchw(
    batch: torch.Tensor,
    crop_size: CropSize,
    same_crop_across_batch: bool = False,
) -> torch.Tensor:
    """
    Random crop for a batch tensor shaped (B, C, H, W).

    If same_crop_across_batch=True, applies the same crop to every item.
    Otherwise, each item gets its own random crop.
    """
    if not isinstance(batch, torch.Tensor):
        raise TypeError("batch must be a torch.Tensor")
    if batch.ndim != 4:
        raise ValueError(f"Expected batch shape (B,C,H,W). Got {tuple(batch.shape)}")

    B, C, H, W = batch.shape
    h, w = _parse_crop_size(crop_size)

    if h > H or w > W:
        raise ValueError(f"Crop {(h, w)} larger than image {(H, W)}")

    if same_crop_across_batch:
        top = torch.randint(0, H - h + 1, (1,)).item()
        left = torch.randint(0, W - w + 1, (1,)).item()
        return batch[:, :, top:top + h, left:left + w]

    # Different crop per item
    crops = []
    for i in range(B):
        top = torch.randint(0, H - h + 1, (1,)).item()
        left = torch.randint(0, W - w + 1, (1,)).item()
        crops.append(batch[i, :, top:top + h, left:left + w])
    return torch.stack(crops, dim=0)


def random_crop_pair(
    img: torch.Tensor,
    mask: torch.Tensor,
    crop_size: CropSize,
) -> tuple[torch.Tensor, torch.Tensor]:
    """
    Apply the SAME random crop to img and mask.

    img: (C, H, W)
    mask: (H, W) or (1, H, W)
    """
    if not isinstance(img, torch.Tensor) or not isinstance(mask, torch.Tensor):
        raise TypeError("img and mask must be torch.Tensors")

    if img.ndim != 3:
        raise ValueError(f"Expected img shape (C,H,W). Got {tuple(img.shape)}")

    c, H, W = img.shape
    h, w = _parse_crop_size(crop_size)

    # Normalize mask to (1, H, W)
    if mask.ndim == 2:
        mask_ = mask.unsqueeze(0)
    elif mask.ndim == 3 and mask.shape[0] in (1,):
        mask_ = mask
    else:
        raise ValueError(f"Expected mask shape (H,W) or (1,H,W). Got {tuple(mask.shape)}")

    if mask_.shape[1] != H or mask_.shape[2] != W:
        raise ValueError("img and mask must have matching H,W")

    if h > H or w > W:
        raise ValueError(f"Crop {(h, w)} larger than image {(H, W)}")

    top = torch.randint(0, H - h + 1, (1,)).item()
    left = torch.randint(0, W - w + 1, (1,)).item()

    cropped_img = img[:, top:top + h, left:left + w]
    cropped_mask = mask_[:, top:top + h, left:left + w]

    # Return mask in same rank as input
    if mask.ndim == 2:
        return cropped_img, cropped_mask.squeeze(0)
    return cropped_img, cropped_mask


if __name__ == "__main__":
    # CHW test
    img = torch.randn(3, 224, 224)
    out = random_crop_chw(img, (112, 112))
    print("CHW:", out.shape)  # torch.Size([3, 112, 112])

    # BCHW test
    batch = torch.randn(4, 3, 224, 224)
    out_b = random_crop_bchw(batch, (112, 112), same_crop_across_batch=False)
    print("BCHW:", out_b.shape)  # torch.Size([4, 3, 112, 112])

    # Pair test: (H,W) mask
    mask2 = torch.randint(0, 2, (224, 224))
    img_c, mask_c = random_crop_pair(img, mask2, (112, 112))
    print("PAIR:", img_c.shape, mask_c.shape)  # (3,112,112) (112,112)
