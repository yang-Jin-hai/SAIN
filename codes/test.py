import argparse
import logging
import os.path as osp
import time
from collections import OrderedDict

from tqdm import tqdm

import options.options as option
import utils.util as util
from data import create_dataloader, create_dataset
from data.util import bgr2ycbcr
from models import create_model
from models.compressor import REALCOMP

#### options
parser = argparse.ArgumentParser()
parser.add_argument('-opt', type=str, required=True, help='Path to options YMAL file.')
parser.add_argument('-format', type=str, required=True, help='Compression Format')
parser.add_argument('-qf', type=int, required=True, help='Compression Quality')
compress_format = parser.parse_args().format
compress_quality = parser.parse_args().qf
opt = option.parse(parser.parse_args().opt, is_train=False)
opt = option.dict_to_nonedict(opt)

util.mkdirs(
    (path for key, path in opt['path'].items()
     if not key == 'experiments_root' and 'pretrain_model' not in key and 'resume' not in key))
util.setup_logger('base', opt['path']['log'], 'test_' + opt['name'], level=logging.INFO,
                  screen=True, tofile=True)
logger = logging.getLogger('base')
logger.info(option.dict2str(opt))

#### Create test dataset and dataloader
test_loaders = []
for phase, dataset_opt in sorted(opt['datasets'].items()):
    test_set = create_dataset(dataset_opt)
    test_loader = create_dataloader(test_set, dataset_opt)
    logger.info('Number of test images in [{:s}]: {:d}'.format(dataset_opt['name'], len(test_set)))
    test_loaders.append(test_loader)

model = create_model(opt)
for test_loader in test_loaders:
    test_set_name = test_loader.dataset.opt['name']
    logger.info('\nTesting [{:s}]...'.format(test_set_name))
    test_start_time = time.time()
    dataset_dir = osp.join(opt['path']['results_root'], test_set_name, compress_format, str(compress_quality))
    util.mkdir(dataset_dir)

    test_results = OrderedDict()
    test_results['psnr'] = []
    test_results['ssim'] = []
    test_results['psnr_y'] = []
    test_results['ssim_y'] = []

    test_results['psnr_lr'] = []
    test_results['ssim_lr'] = []
    test_results['psnr_y_lr'] = []
    test_results['ssim_y_lr'] = []

    for data in tqdm(test_loader, total=len(test_loader)):
        model.feed_data(data)
        img_path = data['GT_path'][0]
        img_name = osp.splitext(osp.basename(img_path))[0]

        visuals = {'GT': model.real_H, 'LR_ref': model.ref_L}
        visuals['LR'] = forw_L = model.downscale(model.real_H)
        if compress_quality == -1:
            visuals['SR'] = fake_H = model.upscale(forw_L, opt['scale'])
        else:
            visuals['SR'] = fake_H = model.upscale(REALCOMP(format=compress_format, quality=compress_quality)(forw_L), opt['scale'])

        sr_img = util.tensor2img(visuals['SR'])  # uint8
        srgt_img = util.tensor2img(visuals['GT'])  # uint8
        lr_img = util.tensor2img(visuals['LR'])  # uint8
        lrgt_img = util.tensor2img(visuals['LR_ref'])  # uint8

        # save images
        suffix = opt['suffix']
        if suffix:
            save_img_path = osp.join(dataset_dir, img_name + suffix + '.png')
        else:
            save_img_path = osp.join(dataset_dir, img_name + '.png')
        util.save_img(sr_img, save_img_path)

        if suffix:
            save_img_path = osp.join(dataset_dir, img_name + suffix + '_GT.png')
        else:
            save_img_path = osp.join(dataset_dir, img_name + '_GT.png')
        util.save_img(srgt_img, save_img_path)

        if suffix:
            save_img_path = osp.join(dataset_dir, img_name + suffix + '_LR.png')
        else:
            save_img_path = osp.join(dataset_dir, img_name + '_LR.png')
        util.save_img(lr_img, save_img_path)

        if suffix:
            save_img_path = osp.join(dataset_dir, img_name + suffix + '_LR_ref.png')
        else:
            save_img_path = osp.join(dataset_dir, img_name + '_LR_ref.png')
        util.save_img(lrgt_img, save_img_path)

        # calculate PSNR and SSIM
        gt_img = util.tensor2img(visuals['GT'])

        gt_img = gt_img / 255.
        sr_img = sr_img / 255.

        lr_img = lr_img / 255.
        lrgt_img = lrgt_img / 255.

        crop_border = opt['crop_border'] if opt['crop_border'] else opt['scale']
        if crop_border == 0:
            cropped_sr_img = sr_img
            cropped_gt_img = gt_img
        else:
            cropped_sr_img = sr_img[crop_border:-crop_border, crop_border:-crop_border, :]
            cropped_gt_img = gt_img[crop_border:-crop_border, crop_border:-crop_border, :]

        psnr = util.calculate_psnr(cropped_sr_img * 255, cropped_gt_img * 255)
        ssim = util.calculate_ssim(cropped_sr_img * 255, cropped_gt_img * 255)
        test_results['psnr'].append(psnr)
        test_results['ssim'].append(ssim)

        # PSNR and SSIM for LR
        psnr_lr = util.calculate_psnr(lr_img * 255, lrgt_img * 255)
        ssim_lr = util.calculate_ssim(lr_img * 255, lrgt_img * 255)
        test_results['psnr_lr'].append(psnr_lr)
        test_results['ssim_lr'].append(ssim_lr)

        if gt_img.shape[2] == 3:  # RGB image
            sr_img_y = bgr2ycbcr(sr_img, only_y=True)
            gt_img_y = bgr2ycbcr(gt_img, only_y=True)
            if crop_border == 0:
                cropped_sr_img_y = sr_img_y
                cropped_gt_img_y = gt_img_y
            else:
                cropped_sr_img_y = sr_img_y[crop_border:-crop_border, crop_border:-crop_border]
                cropped_gt_img_y = gt_img_y[crop_border:-crop_border, crop_border:-crop_border]
            psnr_y = util.calculate_psnr(cropped_sr_img_y * 255, cropped_gt_img_y * 255)
            ssim_y = util.calculate_ssim(cropped_sr_img_y * 255, cropped_gt_img_y * 255)
            test_results['psnr_y'].append(psnr_y)
            test_results['ssim_y'].append(ssim_y)

            lr_img_y = bgr2ycbcr(lr_img, only_y=True)
            lrgt_img_y = bgr2ycbcr(lrgt_img, only_y=True)
            psnr_y_lr = util.calculate_psnr(lr_img_y * 255, lrgt_img_y * 255)
            ssim_y_lr = util.calculate_ssim(lr_img_y * 255, lrgt_img_y * 255)
            test_results['psnr_y_lr'].append(psnr_y_lr)
            test_results['ssim_y_lr'].append(ssim_y_lr)

            logger.info(
                    '{:20s} - PSNR_Y: {:.6f} dB; SSIM_Y: {:.6f}.'.
                format(img_name, psnr_y, ssim_y))
        else:
            logger.info('{:20s} - PSNR: {:.6f} dB; SSIM: {:.6f}.'.format(img_name, psnr, ssim))

    # Average PSNR/SSIM results
    ave_psnr = sum(test_results['psnr']) / len(test_results['psnr'])
    ave_ssim = sum(test_results['ssim']) / len(test_results['ssim'])

    ave_psnr_lr = sum(test_results['psnr_lr']) / len(test_results['psnr_lr'])
    ave_ssim_lr = sum(test_results['ssim_lr']) / len(test_results['ssim_lr'])

    logger.info(
            '----Average PSNR/SSIM results for {}----\n\tpsnr: {:.6f} db; ssim: {:.6f}. LR psnr: {:.6f} db; ssim: {:.6f}.\n'.format(
            test_set_name, ave_psnr, ave_ssim, ave_psnr_lr, ave_ssim_lr))
    if test_results['psnr_y'] and test_results['ssim_y']:
        ave_psnr_y = sum(test_results['psnr_y']) / len(test_results['psnr_y'])
        ave_ssim_y = sum(test_results['ssim_y']) / len(test_results['ssim_y'])

        ave_psnr_y_lr = sum(test_results['psnr_y_lr']) / len(test_results['psnr_y_lr'])
        ave_ssim_y_lr = sum(test_results['ssim_y_lr']) / len(test_results['ssim_y_lr'])
        logger.info(
            '----Y channel, average PSNR/SSIM----\n\tPSNR_Y: {:.6f} dB; SSIM_Y: {:.6f}. LR PSNR_Y: {:.6f} dB; SSIM_Y: {:.6f}.\n'.
            format(ave_psnr_y, ave_ssim_y, ave_psnr_y_lr, ave_ssim_y_lr))
