import torch
from ai_deney.random_cropping import random_crop_chw, random_crop_bchw, random_crop_pair

def test_random_crop_chw_shape():
    img = torch.randn(3, 224, 224)
    out = random_crop_chw(img, (112, 112))
    assert out.shape == (3, 112, 112)

def test_random_crop_bchw_shape():
    batch = torch.randn(4, 3, 224, 224)
    out = random_crop_bchw(batch, (112, 112))
    assert out.shape == (4, 3, 112, 112)

def test_random_crop_pair_mask_hw():
    img = torch.randn(3, 224, 224)
    mask = torch.randint(0, 2, (224, 224))
    img_c, mask_c = random_crop_pair(img, mask, (112, 112))
    assert img_c.shape == (3, 112, 112)
    assert mask_c.shape == (112, 112)

def test_random_crop_pair_mask_1hw():
    img = torch.randn(3, 224, 224)
    mask = torch.randint(0, 2, (1, 224, 224))
    img_c, mask_c = random_crop_pair(img, mask, (112, 112))
    assert img_c.shape == (3, 112, 112)
    assert mask_c.shape == (1, 112, 112)
