# -*- coding: utf-8 -*-
"""


DONE:
- change settings in pynta (like exposure time)
- click and zoom to fixed size (config defined), and a return to fullscreen button

NEXT TIME

TODO:
- separate live view from saving
  through modification of pipeline
- single snapshot option
- live graph of image analysis data (see pyocv version), but not scrolling, but oscilloscope style
- daq settings in config (maybe also keep a gui)
- perhaps it would be nice to show a crosshair when camera is primed to click (add point / zoom)
- ...




"""
import sys
import copy

import json
import os
import time
# from threading import Event

from datetime import datetime

import h5py as h5py
import numpy as np
# from multiprocessing import Queue, Process
import pynta
from pynta import general_stop_event
from pynta.model.experiment.base_experiment import BaseExperiment, DataPipeline, SaveTracksToHDF5, SaveImageToHDF5, SaveDaqToHDF5, SaveTriggerToHDF5, FileWrangler
# from pynta.model.experiment.nanospring_tracking.decorators import (check_camera,
#                                                                      check_not_acquiring,
#                                                                      make_async_thread)

# from pynta.model.experiment.nanospring_tracking.localization import LocateParticles
# from pynta.model.experiment.nanospring_tracking.saver import worker_listener
# from pynta.model.experiment.nanospring_tracking.exceptions import StreamSavingRunning
from pynta.util import get_logger
from pynta import Q_

from pynta.controller.devices.NIDAQ.ni_usb_6216 import NiUsb6216 as DaqController

# import trackpy as tp
from scipy import ndimage
from pynta_drivers import Camera as NativeCamera;



class ContinousTracker:
    def __init__(self, to_track) -> None:
        self.to_track = to_track
    def __call__(self, img):
        for i in range(0, len(self.to_track[0])):
            x = self.to_track[0][i]
            y = self.to_track[1][i]
            rad = 30
            xmin = int(max(0, x - rad))
            xmax = int(min(x + rad, img.shape[1]))
            ymin = int(max(0, y - rad))
            ymax = int(min(y + rad, img.shape[0]))
            # print("{}, {} in image of size {}".format(x,y,img.shape))
            local = img[ymin:ymax, xmin:xmax]
            # print(local)
            amax = np.argmax(local, axis=None)
            # print(amax)
            y_, x_ = np.unravel_index(amax, local.shape)
            # print("offsets are {}, {}, position {}, {}, intenity {}".format(x_,y_, x, y, np.max(local)))
            # Update the coordinate to the (new) location of the maximum
            #if local[(x_,y_)] > 1:
            self.to_track[1][i] = ymin + y_
            self.to_track[0][i] = xmin + x_
        return self.to_track

class ContinousTracker2:
    def __init__(self, to_track, rad=32) -> None:
        self.to_track = to_track
        self.rad = rad
    def __call__(self, img):
        for i in range(0, len(self.to_track[0])):
            x = self.to_track[0][i]
            y = self.to_track[1][i]
            xmin = int(max(0, x - self.rad))
            xmax = int(min(x + self.rad, img.shape[1]))
            ymin = int(max(0, y - self.rad))
            ymax = int(min(y + self.rad, img.shape[0]))
            # print("{}, {} in image of size {}".format(x,y,img.shape))
            local = img[ymin:ymax, xmin:xmax]
            if local.sum() > 0:
                (y,x) = ndimage.measurements.center_of_mass(local)
                print("offsets are {}, {}, summed intenity {}".format(self.rad-x-0.5, self.rad-y-0.5, np.sum(local)))
                self.to_track[1][i] -= self.rad-y-0.5
                self.to_track[0][i] -= self.rad-x-0.5
                self.to_track[2][i] = np.sum(local)
        return self.to_track




class Experiment(BaseExperiment):
    BACKGROUND_NO_CORRECTION = 0  # No background correction
    BACKGROUND_SINGLE_SNAP = 1

    def __init__(self, filename=None):
        self.config = {}  # Dictionary storing the configuration of the experiment
        self.logger = get_logger(name=__name__)
        self.load_configuration(filename)
        self.camera = NativeCamera(self.config["camera"]['model'])  # This will hold the model for the camera
        self.camera.set_output_trigger()
        # ham = self.camera.as_hamamatsu()
        # ham.set_prop(....);

        self.camera.set_roi([int(self.config["camera"]["roi_x1"]), int(self.config["camera"]["roi_x2"])], [int(self.config["camera"]["roi_y1"]), int(self.config["camera"]["roi_y2"])])
        self.camera.set_exposure(float(Q_(self.config["camera"]["exposure_time"]).m_as("seconds")))
        self.daq_controller = DaqController()
        # self.current_height = None
        # self.current_width = None
        # self.max_width = None
        # self.max_height = None
        super().__init__(filename)
        self.temp_image = None
        self.tracked_locations = ([],[],[])
        save_path = self.config.get('saving', {}).get('directory', '')
        if not os.path.exists(save_path):
            self.logger.warning('save directory does not exist, falling back to parent directory')
            save_path = pynta.parent_path
        save_name = self.config.get('saving', {}).get('filename_tracks', 'output')
        filename = os.path.join(save_path, save_name)
        self.hdf5 = FileWrangler(filename)
        self._pipeline = DataPipeline(self)

    def update_config(self, **kwargs):
        old_camera_conf = self.config['camera'].copy()
        self.logger.info('Updating config')
        self.logger.debug('Config params: {}'.format(kwargs))
        self.config.update(**kwargs)
        if self.config['camera'] != old_camera_conf:
            self.camera.set_roi([int(self.config["camera"]["roi_x1"]), int(self.config["camera"]["roi_x2"])],
                                [int(self.config["camera"]["roi_y1"]), int(self.config["camera"]["roi_y2"])])
            self.camera.set_exposure(float(Q_(self.config["camera"]["exposure_time"]).m_as("seconds")))

    def gui_file(self):
        return "testing"

    def set_zoom(self, coords):
        x, y = coords
        x = min(int(x), self.max_width - self.config['camera']['zoom_width']//2)
        left = max(0, x - self.config['camera']['zoom_width']//2)
        right = min(self.max_width, left + self.config['camera']['zoom_width'])
        y = min(int(y), self.max_height - self.config['camera']['zoom_height'] // 2)
        top = max(0, y - self.config['camera']['zoom_height'] // 2)
        bottom = min(self.max_height, top + self.config['camera']['zoom_height'])
        print("Zooming ROI to", left, right, top, bottom)
        self.set_roi([left, right], [top, bottom])

    def set_roi(self, X, Y):
        """ Sets the region of interest of the camera, provided that the camera supports cropping. All the technicalities
        should be addressed on the camera model, not in this method.

        :param list X: horizontal position for the start and end of the cropping
        :param list Y: vertical position for the start and end of the cropping
        :raises ValueError: if either dimension of the cropping goes out of the camera total amount of pixels
        :returns: The final cropping dimensions, it may be that the camera limits the user desires
        """

        # self.logger.debug('Setting new camera ROI to x={},y={}'.format(X, Y))
        self.camera.set_roi(X, Y)
        self.current_width, self.current_height = self.camera.get_size()
        self.logger.debug('New camera width: {}px, height: {}px'.format(self.current_width, self.current_height))
        self.temp_image = np.zeros((self.current_width, self.current_height), dtype=np.uint16)
        self.config['camera']['roi_x1'] = X[0]
        self.config['camera']['roi_x2'] = X[1]
        self.config['camera']['roi_y1'] = Y[0]
        self.config['camera']['roi_y2'] = Y[1]


    def clear_roi(self):
        """ Clears the region of interest and returns to the full frame of the camera.
        """
        self.logger.info('Clearing ROI settings')
        X = [0, self.max_width]
        Y = [0, self.max_height]
        self.set_roi(X, Y)

        # @make_async_thread
    def snap(self):
        """ Snap a single frame.
        """
        img = np.zeros(self.camera.get_size(), dtype=np.uint16, order='C')
        self.camera.snap_into(img)
        self.temp_image = img

    #@make_async_thread
    # @check_not_acquiring
    # @check_camera
    def start_free_run(self):
        """ Starts continuous acquisition from the camera, but it is not being saved. This method is the workhorse
        of the program. While this method runs on its own thread, it will broadcast the images to be consumed by other
        methods. In this way it is possible to continuously save to hard drive, track particles, etc.
        """
        # return self.start_capture()
        x, y = self.camera.get_size()
        bytes_per_frame = x*y*2
        bytes_to_buffer = 1024*1024*128
        self.camera.start_stream(int(bytes_to_buffer/bytes_per_frame), self._pipeline)


    def start_capture(self):
    #   self.camera.stream_into(self.temp_image)
        aqcuisition = self.hdf5.start_new_aquisition()
        # self.daq_controller.set_processing_function(SaveDaqToHDF5(aqcuisition, self.daq_controller))
        self.save_trigger_object = SaveTriggerToHDF5(aqcuisition, self.daq_controller)
        self.daq_controller.set_trigger_processing_function(self.save_trigger_object)

        # def temp(img_data):
        #     return SaveImageToHDF5(aqcuisition, img_data, self.config['camera']['save_every_Nth_frame'])
        #
        # self._pipeline.set_save_img_func(temp)

        # Equivalent of the code above, but using a lambda-function:
        self._pipeline.set_save_img_func(lambda img: SaveImageToHDF5(aqcuisition, img, self.config['camera']['save_every_Nth_frame']))

        # self.tracking = True
        # self.tracking = False
        # def update_trck(df):
        #     self.tracked_locations = df
        #     return df

        # pipeline = DataPipeline([SaveImageToHDF5(aqcuisition, self.camera, 10),update_img, ContinousTracker2(self.tracked_locations, rad=50), SaveTracksToHDF5(aqcuisition)])
        # x, y = self.camera.get_size()
        # bytes_per_frame = x*y*2
        # bytes_to_buffer = 1024*1024*128
    #     self.camera.start_stream(int(bytes_to_buffer/bytes_per_frame), pipeline)

    # @property
    # def temp_locations(self):
    #     return self.localize_particles_image(self.temp_image)

    def stop_free_run(self):
        """ Stops the free run by setting the ``_stop_event``. It is basically a convenience method to avoid
        having users dealing with somewhat lower level threading options.
        """
        self.camera.stop_stream()
        self.daq_controller.set_trigger_processing_function(None)
        self.daq_controller.set_processing_function(None)
        # self.save_trigger_object.add_finished_timestamp() ########################################################################################
        print("stream stopped in python!")

    def save_image(self):
        """ Saves the last acquired image. The file to which it is going to be saved is defined in the config.
        """
        # if self.temp_image:
        #     self.logger.info('Saving last acquired image')
        #     # Data will be appended to existing file
        #     file_name = self.config['saving']['filename_photo'] + '.hdf5'
        #     file_dir = self.config['saving']['directory']
        #     if not os.path.exists(file_dir):
        #         os.makedirs(file_dir)
        #         self.logger.debug('Created directory {}'.format(file_dir))

        #     with h5py.File(os.path.join(file_dir, file_name), "a") as f:
        #         now = str(datetime.now())
        #         g = f.create_group(now)
        #         g.create_dataset('image', data=self.temp_image)
        #         g.create_dataset('metadata', data=json.dumps(self.config))
        #         f.flush()
        #     self.logger.debug('Saved image to {}'.format(os.path.join(file_dir, file_name)))
        # else:
        #     self.logger.warning('Tried to save an image, but no image was acquired yet.')

    def add_monitor_coordinate(self, coord):
        self.tracked_locations[0].append(coord[0])
        self.tracked_locations[1].append(coord[1])
        self.tracked_locations[2].append(0.0)
    def clear_monitor_coordinates(self):
        self.tracked_locations[0].clear()
        self.tracked_locations[1].clear()
        self.tracked_locations[2].clear()

    def save_stream(self):
        """ Saves the queue to a file continuously. This is an async function, that can be triggered before starting
        the stream. It relies on the multiprocess library. It uses a queue in order to get the data to be saved.
        In normal operation, it should be used together with ``add_to_stream_queue``.
        """
        aqcuisition = self.hdf5.start_new_aquisition()
        # self.save_trigger_object = SaveTriggerToHDF5(aqcuisition, self.daq_controller)
        # self.daq_controller.set_trigger_processing_function(self.save_trigger_object)

        # def temp(img_data):
        #     return SaveImageToHDF5(aqcuisition, img_data, self.config['camera']['save_every_Nth_frame'])
        #
        # self._pipeline.set_save_img_func(temp)

        # Equivalent of the code above, but using a lambda-function:
        self._pipeline.set_save_img_func(
            lambda img: SaveImageToHDF5(aqcuisition, img, self.config['camera']['save_every_Nth_frame']))

        # if self.save_stream_running:
        #     self.logger.warning('Tried to start a new instance of save stream')
        #     raise StreamSavingRunning('You tried to start a new process for stream saving')

        # self.logger.info('Starting to save the stream')
        # file_name = self.config['saving']['filename_video'] + '.hdf5'
        # file_dir = self.config['saving']['directory']
        # if not os.path.exists(file_dir):
        #     os.makedirs(file_dir)
        #     self.logger.debug('Created directory {}'.format(file_dir))
        # file_path = os.path.join(file_dir, file_name)
        # max_memory = self.config['saving']['max_memory']

        # self.stream_saving_process = Process(target=worker_listener,
        #                                      args=(file_path, json.dumps(self.config), 'free_run'),
        #                                      kwargs={'max_memory': max_memory})
        # self.stream_saving_process.start()
        # self.logger.debug('Started the stream saving process')

    def stop_save_stream(self):
        """ Stops saving the stream.
        """
        self._pipeline.set_save_img_func(None)
        self.daq_controller.set_trigger_processing_function(None)

        # if self.save_stream_running:
        #     self.logger.info('Stopping the saving stream process')
        #     self.saver_queue.put('Exit')
        #     self.publisher.publish('free_run', 'stop')
        #     return
        # self.logger.info('The saving stream is not running. Nothing will be done.')

    def start_tracking(self):
        """ Starts the tracking of the particles
        """
        # self.tracking = True
        # self.location.start_tracking('free_run')

    def stop_tracking(self):
        pass
        # self.tracking = False
        # self.location.stop_tracking()

    def start_saving_location(self):
        pass
        # self.saving_location = True
        # file_name = self.config['saving']['filename_tracks'] + '.hdf5'
        # file_dir = self.config['saving']['directory']
        # if not os.path.exists(file_dir):
        #     os.makedirs(file_dir)
        #     self.logger.debug('Created directory {}'.format(file_dir))
        # file_path = os.path.join(file_dir, file_name)
        #self.location.start_saving(file_path, json.dumps(self.config))

    def stop_saving_location(self):
        pass
        # self.saving_location = False
        #self.location.stop_saving()

    def localize_particles_image(self, image=None):
        """
        when complete should localize in the image based on a simple peak-finder

        """
        pass

    @property
    def save_stream_running(self):
        # if self.stream_saving_process is not None:
        #     try:
        #         return self.stream_saving_process.is_alive()
        #     except:
        #         return False
        return False

    @property
    def link_particles_running(self):
        # if self.link_particles_process is not None:
        #     try:
        #         return self.link_particles_process.is_alive()
        #     except:
        #         return False
        return False

    def stop_link_particles(self):
        """ Stops the linking process.
        """
        # if self.link_particles_running:
        #     self.logger.info('Stopping the linking particles process')
        #     self.locations_queue.put('Exit')
        #     return
        self.logger.warning('The linking particles process is not running. Nothing will be done.')

    def empty_saver_queue(self):
        """ Empties the queue where the data from the movie is being stored.
        """
        # if not self.saver_queue.empty():
        #     self.logger.info('Clearing the saver queue')
        #     self.logger.debug('Current saver queue length: {}'.format(self.saver_queue.qsize()))
        #     while not self.saver_queue.empty() or self.saver_queue.qsize() > 0:
        #         self.saver_queue.get()
        #     self.logger.debug('Saver queue cleared')

    def empty_locations_queue(self):
        """ Empties the queue with location data.
        """
        # if not self.locations_queue.empty():
        #     self.logger.info('Location queue not empty. Cleaning.')
        #     self.logger.debug('Current location queue length: {}'.format(self.locations_queue.qsize()))
        #     while not self.locations_queue.empty():
        #         self.locations_queue.get()
        #     self.logger.debug('Location queue cleared')


    def check_background(self):
        """ Checks whether the background is set.
        """

        # if self.do_background_correction:
        #     self.logger.info('Setting up the background corretion')
        #     if self.background_method == self.BACKGROUND_SINGLE_SNAP:
        #         self.logger.debug('Background single snap')
        #         if self.background is None or self.background.shape != [self.current_width, self.current_height]:
        #             self.logger.warning('Background not set. Defaulting to no background...')
        #             self.background = None
        #             self.do_background_correction = False

    def finalize(self):
        # general_stop_event.set()
        # self.monitoring_pixels = False
        # self.stop_free_run()
        # time.sleep(.5)
        # self.stop_save_stream()
        #self.location.finalize()
        self.camera.stop_stream()
        self.daq_controller.stop_all()
        super().finalize()

    def sysexcept(self, exc_type, exc_value, exc_traceback):
        self.logger.exception('Got an unhandled exception: {}'.format(exc_type))
        self.logger.exception('Traceback: {}'.format(exc_traceback))
        self.logger.exception('Value: {}'.format(exc_value))
        self.__exit__()
        sys.exit()

# CLASSES THAT DON'T APPEAR TO BE USED ANYMORE:

# class ImageBuffer:
#     def __init__(self, buffer = None) -> None:
#         self.buffer = buffer
#     def __call__(self, image):
#         if self.buffer is None:
#             # print("setting buffer as it was empty")
#             self.buffer = np.copy(image)
#         else:
#             np.copyto(self.buffer, image, casting='no')
#         return image

# class Track:
#     def __init__(self, diameter = 11) -> None:
#         self.diameter = diameter
#     def __call__(self, image):
#         return tp.locate(image, self.diameter)

# class Batch:
#     def __init__(self, number) -> None:
#         self.number = number
#         self.buffer = None
#         self.index = 0
#     def __call__(self, data):
#         if self.buffer is None:
#             self.buffer = np.zeros((self.number,)+data.shape, data.dtype)
#         self.buffer[self.index,:] = data
#         self.index += 1
