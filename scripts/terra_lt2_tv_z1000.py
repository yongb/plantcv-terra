#!/usr/bin/env python

import cv2
import plantcv as pcv
import numpy as np
import argparse


# Parse command-line arguments
def options():
    parser = argparse.ArgumentParser(description="Process side-view images from the TERRA-REF LT2 experiment.")
    parser.add_argument("-i", "--image", help="Input VIS image file.", required=True)
    parser.add_argument("-r", "--result", help="VIS result file.", required=True)
    parser.add_argument("-r2", "--coresult", help="NIR result file for the co-processed image.", required=True)
    parser.add_argument("-o", "--outdir", help="Output directory for image files.", required=False)
    parser.add_argument("-w", "--writeimg", help="Create output images.", default=False, action="store_true")
    parser.add_argument("-d", "--debug", help="Turn on debug, prints intermediate images.", default=None)
    args = parser.parse_args()

    # If debug is not None then set debug mode to print
    if args.debug is not None:
        args.debug = "print"

    return args


# Helper function to fit VIS images onto NIR images
def crop_sides_equally(mask, nir, device, debug):
    device += 1
    # NumPy refers to y first then x
    mask_shape = np.shape(mask)  # type: tuple
    nir_shape = np.shape(nir)  # type: tuple
    final_y = mask_shape[0]
    final_x = mask_shape[1]
    difference_x = final_x - nir_shape[1]
    difference_y = final_y - nir_shape[0]
    if difference_x % 2 == 0:
        x1 = difference_x / 2
        x2 = difference_x / 2
    else:
        x1 = difference_x / 2
        x2 = (difference_x / 2) + 1

    if difference_y % 2 == 0:
        y1 = difference_y / 2
        y2 = difference_y / 2
    else:
        y1 = difference_y / 2
        y2 = (difference_y / 2) + 1
    crop_img = mask[y1:final_y - y2, x1:final_x - x2]

    if debug == "print":
        pcv.print_image(crop_img, str(device) + "_crop_sides_equally.png")
    elif debug == "plot":
        pcv.plot_image(crop_img, cmap="gray")

    return device, crop_img


# Helper function to fit VIS images onto NIR images
def conv_ratio(y=606.0, x=508.0, conv_x=1.125, conv_y=1.125, rat=1):
    prop2 = (x / 2056)
    prop1 = (y / 2454)
    prop2 = prop2 * (conv_y * rat)
    prop1 = prop1 * (conv_x * rat)
    return prop2, prop1


# Remove contours completely contained within a region of interest
def remove_countors_roi(mask, contours, hierarchy, roi, device, debug=None):
    clean_mask = np.copy(mask)
    # Loop over all contours in the image
    for n, contour in enumerate(contours):
        # This is the number of vertices in the contour
        contour_points = len(contour) - 1
        # Generate a list of x, y coordinates
        stack = np.vstack(contour)
        tests = []
        # Loop over the vertices for the contour and do a point polygon test
        for i in range(0, contour_points):
            # The point polygon test returns
            # 1 if the contour vertex is inside the ROI contour
            # 0 if the contour vertex is on the ROI contour
            # -1 if the contour vertex is outside the ROI contour
            pptest = cv2.pointPolygonTest(contour=roi[0], pt=(stack[i][0], stack[i][1]), measureDist=False)
            # Append the test result to the list of point polygon tests for this contour
            tests.append(pptest)
        # If all of the point polygon tests have a value of 1, then all the contour vertices are in the ROI
        if all(t == 1 for t in tests):
            # Fill in the contour as black
            cv2.drawContours(image=clean_mask, contours=contours, contourIdx=n, color=0, thickness=-1, lineType=8,
                             hierarchy=hierarchy)
    if debug == "print":
        pcv.print_image(filename=str(device) + "_remove_contours.png", img=clean_mask)
    elif debug == "plot":
        pcv.plot_image(clean_mask, cmap='gray')

    return device, clean_mask


# The main workflow
def main():
    # Initialize device
    device = 0

    # Parse command-line options
    args = options()

    # Read image
    img, path, filename = pcv.readimage(filename=args.image, debug=args.debug)

    # Convert RGB to LAB and extract the Green-Magenta channel
    device, green_channel = pcv.rgb2gray_lab(img=img, channel="a", device=device, debug=args.debug)

    # Threshold the Green-Magenta image to isolate damaged tissues
    device, green_thresh = pcv.binary_threshold(img=green_channel, threshold=137, maxValue=255, object_type="light",
                                                device=device, debug=args.debug)

    # Extract core plant region from the image to preserve delicate plant features during filtering
    device += 1
    plant_region = green_thresh[250:2000, 250:2250]
    if args.debug is not None:
        pcv.print_image(filename=str(device) + "_extract_plant_region.png", img=plant_region)

    # Use a Gaussian blur to disrupt the strong edge features in the cabinet
    device, blur_gaussian = pcv.gaussian_blur(device=device, img=green_thresh, ksize=(7, 7), sigmax=0, sigmay=None,
                                              debug=args.debug)

    # Threshold the blurred image to remove features that were blurred
    device, blur_thresholded = pcv.binary_threshold(img=blur_gaussian, threshold=250, maxValue=255, object_type="light",
                                                    device=device, debug=args.debug)

    # Add the plant region back in to the filtered image
    device += 1
    blur_thresholded[250:2000, 250:2250] = plant_region
    if args.debug is not None:
        pcv.print_image(filename=str(device) + "_replace_plant_region.png", img=blur_thresholded)

    # Define an ROI for the brass stopper
    device, stopper_roi, stopper_hierarchy = pcv.define_roi(img=img, shape="rectangle", device=device, roi=None,
                                                            roi_input="default", debug=args.debug, adjust=True,
                                                            x_adj=1480, y_adj=850, w_adj=-870, h_adj=-1075)

    # Identify all remaining contours in the binary image
    device, contours, hierarchy = pcv.find_objects(img=img, mask=np.copy(blur_thresholded), device=device,
                                                   debug=args.debug)

    # Remove stopper contours
    device, remove_stopper_mask = remove_countors_roi(mask=blur_thresholded, contours=contours, hierarchy=hierarchy,
                                                      roi=stopper_roi, device=device, debug=args.debug)

    # Threshold image
    device, green_inv_thresh = pcv.binary_threshold(img=green_channel, threshold=120, maxValue=255, object_type="dark",
                                                    device=device, debug=args.debug)

    # Merge the plant and damaged plant masks
    device, green_merged = pcv.logical_or(img1=green_inv_thresh, img2=remove_stopper_mask, device=device,
                                          debug=args.debug)

    # Extract core plant region from the image to preserve delicate plant features during filtering
    device += 1
    plant_region = green_merged[250:2000, 250:2250]
    if args.debug is not None:
        pcv.print_image(filename=str(device) + "_extract_plant_region.png", img=plant_region)

    # Use a Gaussian blur to disrupt the strong edge features in the cabinet
    device, blur_gaussian = pcv.gaussian_blur(device=device, img=green_merged, ksize=(7, 7), sigmax=0, sigmay=None,
                                              debug=args.debug)

    # Threshold the blurred image to remove features that were blurred
    device, blur_thresholded = pcv.binary_threshold(img=blur_gaussian, threshold=250, maxValue=255, object_type="light",
                                                    device=device, debug=args.debug)

    # Add the plant region back in to the filtered image
    blur_thresholded[250:2000, 250:2250] = plant_region
    if args.debug is not None:
        pcv.print_image(filename=str(device) + "_replace_plant_region.png", img=blur_thresholded)

    # Use a median blur to breakup the horizontal and vertical lines caused by shadows from the track edges
    device, med_blur = pcv.median_blur(img=blur_thresholded, ksize=7, device=device, debug=args.debug)

    # Fill in small contours
    device, green_fill_50 = pcv.fill(img=np.copy(med_blur), mask=np.copy(med_blur), size=100, device=device,
                                     debug=args.debug)

    # Identify remaining objects
    device, contours, contour_hierarchy = pcv.find_objects(img=img, mask=np.copy(green_fill_50), device=device,
                                                           debug=args.debug)

    # Define an ROI for the brass stopper
    device, stopper_roi, stopper_hierarchy = pcv.define_roi(img=img, shape="rectangle", device=device, roi=None,
                                                            roi_input="default", debug=args.debug, adjust=True,
                                                            x_adj=1480, y_adj=850, w_adj=-870, h_adj=-1075)

    device, remove_stopper_mask = remove_countors_roi(mask=green_fill_50, contours=contours,
                                                      hierarchy=contour_hierarchy, roi=stopper_roi, device=device,
                                                      debug=args.debug)

    # Define an ROI for a screw hole
    device, screw_roi, screw_hierarchy = pcv.define_roi(img=img, shape="rectangle", device=device, roi=None,
                                                        roi_input="default", debug=args.debug, adjust=True, x_adj=2000,
                                                        y_adj=945, w_adj=-220, h_adj=-880)

    device, remove_screw_mask = remove_countors_roi(mask=remove_stopper_mask, contours=contours,
                                                    hierarchy=contour_hierarchy, roi=screw_roi, device=device,
                                                    debug=args.debug)

    # Define an ROI for a screw hole
    device, screw_roi, screw_hierarchy = pcv.define_roi(img=img, shape="rectangle", device=device, roi=None,
                                                        roi_input="default", debug=args.debug, adjust=True, x_adj=1660,
                                                        y_adj=990, w_adj=-600, h_adj=-1000)

    device, remove_screw_mask = remove_countors_roi(mask=remove_screw_mask, contours=contours,
                                                    hierarchy=contour_hierarchy, roi=screw_roi, device=device,
                                                    debug=args.debug)

    # Identify objects
    device, contours, contour_hierarchy = pcv.find_objects(img=img, mask=remove_screw_mask, device=device,
                                                           debug=args.debug)

    # Define ROI
    device, roi, roi_hierarchy = pcv.define_roi(img=img, shape="rectangle", device=device, roi=None,
                                                roi_input="default", debug=args.debug, adjust=True, x_adj=565,
                                                y_adj=200, w_adj=-520, h_adj=-250)

    # Decide which objects to keep
    device, roi_contours, roi_contour_hierarchy, _, _ = pcv.roi_objects(img=img, roi_type="partial", roi_contour=roi,
                                                                        roi_hierarchy=roi_hierarchy,
                                                                        object_contour=contours,
                                                                        obj_hierarchy=contour_hierarchy,
                                                                        device=device, debug=args.debug)

    # If there are no contours left we cannot measure anything
    if len(roi_contours) > 0:
        # Object combine kept objects
        device, plant_contour, plant_mask = pcv.object_composition(img=img, contours=roi_contours,
                                                                   hierarchy=roi_contour_hierarchy, device=device,
                                                                   debug=args.debug)

        outfile = False
        if args.writeimg:
            outfile = args.outdir + "/" + filename

        # Find shape properties, output shape image (optional)
        device, shape_header, shape_data, shape_img = pcv.analyze_object(img=img, imgname=args.image, obj=plant_contour,
                                                                         mask=plant_mask, device=device,
                                                                         debug=args.debug, filename=outfile)

        # Determine color properties: Histograms, Color Slices and Pseudocolored Images,
        # output color analyzed images (optional)
        device, color_header, color_data, color_img = pcv.analyze_color(img=img, imgname=args.image, mask=plant_mask,
                                                                        bins=256, device=device, debug=args.debug,
                                                                        hist_plot_type=None, pseudo_channel="v",
                                                                        pseudo_bkg="img", resolution=300,
                                                                        filename=outfile)

        # Output shape and color data
        result = open(args.result, "a")
        result.write('\t'.join(map(str, shape_header)) + "\n")
        result.write('\t'.join(map(str, shape_data)) + "\n")
        for row in shape_img:
            result.write('\t'.join(map(str, row)) + "\n")
        result.write('\t'.join(map(str, color_header)) + "\n")
        result.write('\t'.join(map(str, color_data)) + "\n")
        for row in color_img:
            result.write('\t'.join(map(str, row)) + "\n")
        result.close()

        # Find matching NIR image
        device, nirpath = pcv.get_nir(path=path, filename=filename, device=device, debug=args.debug)
        nir_rgb, nir_path, nir_filename = pcv.readimage(nirpath)
        nir_img = cv2.imread(nirpath, 0)

        # Make mask glovelike in proportions via dilation
        device, d_mask = pcv.dilate(plant_mask, kernel=1, i=0, device=device, debug=args.debug)

        # Resize mask
        prop2, prop1 = conv_ratio()
        device, nmask = pcv.resize(img=d_mask, resize_x=prop1, resize_y=prop2, device=device, debug=args.debug)

        # Convert the resized mask to a binary mask
        device, bmask = pcv.binary_threshold(img=nmask, threshold=0, maxValue=255, object_type="light",
                                             device=device, debug=args.debug)

        device, crop_img = crop_sides_equally(mask=bmask, nir=nir_img, device=device, debug=args.debug)

        # position, and crop mask
        device, newmask = pcv.crop_position_mask(img=nir_img, mask=crop_img, device=device, x=2, y=0, v_pos="bottom",
                                                 h_pos="right", debug=args.debug)

        # Identify objects
        device, nir_objects, nir_hierarchy = pcv.find_objects(img=nir_rgb, mask=newmask, device=device,
                                                              debug=args.debug)

        # Object combine kept objects
        device, nir_combined, nir_combinedmask = pcv.object_composition(img=nir_rgb, contours=nir_objects,
                                                                        hierarchy=nir_hierarchy, device=device,
                                                                        debug=args.debug)

        # Analyze NIR signal data
        device, nhist_header, nhist_data, nir_imgs = pcv.analyze_NIR_intensity(img=nir_img, rgbimg=nir_rgb,
                                                                               mask=nir_combinedmask, bins=256,
                                                                               device=device, histplot=False,
                                                                               debug=args.debug, filename=outfile)

        # Analyze the shape of the plant contour from the NIR image
        device, nshape_header, nshape_data, nir_shape = pcv.analyze_object(img=nir_img, imgname=nir_filename,
                                                                           obj=nir_combined, mask=nir_combinedmask,
                                                                           device=device, debug=args.debug,
                                                                           filename=outfile)

        # Write NIR data to co-results file
        coresult = open(args.coresult, "a")
        coresult.write('\t'.join(map(str, nhist_header)) + "\n")
        coresult.write('\t'.join(map(str, nhist_data)) + "\n")
        for row in nir_imgs:
            coresult.write('\t'.join(map(str, row)) + "\n")
        coresult.write('\t'.join(map(str, nshape_header)) + "\n")
        coresult.write('\t'.join(map(str, nshape_data)) + "\n")
        coresult.write('\t'.join(map(str, nir_shape)) + "\n")
        coresult.close()


if __name__ == '__main__':
    main()
