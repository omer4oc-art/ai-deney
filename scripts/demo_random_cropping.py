import torch
from ai_deney.random_cropping import random_crop_chw, random_crop_bchw, random_crop_pair

def main():
    img = torch.randn(3, 224, 224)
    print("CHW:", random_crop_chw(img, (112, 112)).shape)

    batch = torch.randn(4, 3, 224, 224)
    print("BCHW:", random_crop_bchw(batch, (112, 112)).shape)

    mask = torch.randint(0, 2, (224, 224))
    img_c, mask_c = random_crop_pair(img, mask, (112, 112))
    print("PAIR:", img_c.shape, mask_c.shape)

if __name__ == "__main__":
    main()
