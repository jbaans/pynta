"""
Equivalent of main.py which includes NI DAQ and does not use SubscriberThread)


"""
import logging
import os
from PyQt5 import uic
from PyQt5.QtCore import QThreadPool
from pynta.util.QWorkerThread import Worker
from PyQt5.QtWidgets import QMainWindow, QStatusBar
from pynta.util.log import get_logger
import time

import numpy as np

from pynta.view.GUI.dcam_main_gui import MainWindowGUI
from pynta.model.daqs.signal_generator.ni import Ni6216Generator

class MainWindow(MainWindowGUI):
    def __init__(self, experiment):
        """
        :param nanoparticle_tracking.model.experiment.win_nanocet.NPTracking experiment: Experiment class
        """
        super().__init__(experiment.config['GUI']['refresh_time'])
        
        # Create a threadpool to put threads for Workers in
        self.threadpool = QThreadPool()
        print("Multithreading with maximum %d threads" % self.threadpool.maxThreadCount())

        self.experiment = experiment
        self.plot_widget.set_model(experiment.daq_controller)
        self.plot_widget.flush_settings()
        self.signal_gen_widget.set_model(Ni6216Generator(experiment.daq_controller))
        self.camera_viewer_widget.setup_roi_lines([self.experiment.max_width, self.experiment.max_height])
        # self.config_tracking_widget.update_config(self.experiment.config['tracking'])
        self.config_widget.update_config(self.experiment.config)
        self.actionConfiguration.triggered.connect(self.show_config)
        # self.tracking = False

        # self.actionAdd_Monitor_Point.triggered.connect(self.zoom)  # REMOVE THIS AGAIN !!!!!!!!!!!!!!!!!!!!!!!!!!!

        self.camera_viewer_widget.setup_mouse_click()
        self.load_measument_methods()

        self.experiment.clear_statusbar = self.statusBar.clearMessage


    # def load_measument_methods(self):
    #     for name in self.experiment.measurement_methods:
    #         self.measurement_combo.addItem(name)
    #     def runmeas():
    #         name = self.measurement_combo.currentText()
    #         return self.experiment.measurement_methods[name]()
    #     self.measurement_run.clicked.connect(runmeas)
    #     self.load_measument_methods()

    def load_measument_methods(self):
        """
        Add the "measurement"-methods defined in the experiment class to the dropdown box and link the Run-button to call those methods
        """
        for name in self.experiment.measurement_methods:
            self.measurement_combo.addItem(name)

        def runmeas():
            name = self.measurement_combo.currentText()
            measurement_method = self.experiment.measurement_methods[name]
            worker = Worker(measurement_method)
            # add worker to the threadpool and have it started.
            # This automatically calls the worker.run() method with *args and *kwargs set using __init__()
            self.threadpool.start(worker)

        self.measurement_run.clicked.connect(runmeas)

    def zoom_ROI_prime(self):
        """ method called by actionZoom, which primes viewer widget to call zoom_ROI_callback on next click"""
        self.logger.info('Click to zoom ROI.')
        self.camera_viewer_widget.connect_mouse_clicked(self.zoom_ROI_callback)

    def zoom_ROI_callback(self, coords):
        self.logger.info("Zooming to coordinate {}".format(coords))
        # IDEA: stop camera if running
        # FAILED ATTEMPT
        # was_running = self.experiment.camera.is_streaming()
        # print('was running', was_running)
        # if was_running:
        #     self.stop_movie()
        #     time.sleep(1)

        self.experiment.set_zoom(coords)
        self.camera_viewer_widget.connect_mouse_clicked(None)
        # IDEA; start camera if it was running before
        # FAILED ATTEMPT:
        # if was_running:
        #     self.start_movie()

    def show_config(self):
        self.config_widget.update_config(self.experiment.config)
        self.config_widget.show()

    def add_monitor_point(self):
        """prime viewer widget with add_monitor_point_callback on next click on screen"""
        self.logger.info('Click to add point.')
        self.camera_viewer_widget.connect_mouse_clicked(self.add_monitor_point_callback)

    def add_monitor_point_callback(self, coord):
        self.logger.info("Adding coordinate {}".format(coord))
        self.experiment.add_monitor_coordinate(coord)
        self.camera_viewer_widget.connect_mouse_clicked(None)
        # print(self.experiment.config['monitor_coordinates'])

    def clear_monitor_points(self):
        self.experiment.clear_monitor_coordinates()

    def initialize_camera(self):
        self.logger.debug("initialize camera called")
        # self.experiment.initialize_camera()

    def snap(self):
        self.experiment.snap()

    def update_gui(self):
        # if self.experiment.temp_image is not None:
        #     if self.experiment.bg_correction:
        #         self.camera_viewer_widget.update_image(self.experiment.temp_image.astype(np.int16) - self.experiment.bg_image)
        #     else:
        #         self.camera_viewer_widget.update_image(self.experiment.temp_image)
        #     self.experiment.temp_image = None
        if self.experiment._show_snap:
            self.camera_viewer_widget.update_image(self.experiment.snap_image)
            return

        if self.experiment.temp_image is not None:
            self.camera_viewer_widget.update_image(self.experiment.temp_image)

        # if self.experiment.tracked_locations[0]:
                # locations = self.experiment.temp_locations
        self.camera_viewer_widget.draw_target_pointer(self.experiment.tracked_locations)
            # if hasattr(self.experiment, "monitoring_pixels"):
                # if self.experiment.monitoring_pixels:
                    # monitor_values = self.experiment.temp_monitor_values
                    # self.analysis_dock_widget.intensities_widget.update_graph(monitor_values)

    def toggle_movie(self, state):
        if state:
            self.experiment.start_free_run()
            self.actionStart_Movie.setToolTip('Stop Movie')
        else:
            self.experiment.stop_free_run()
            self.actionStart_Movie.setToolTip('Start Movie')
            self.actionStart_Movie.setChecked(False)

    # We make sure that out of the next two methods only one can be active at the same time

    def toggle_background(self, state):
        self.logger.info('Turning BG reduction ' + ['off', 'on'][state])
        self.experiment.toggle_background(state)
        self.actionToggleLiveImageProcessing.setEnabled(not state)  # disable toggle_live_img_process while toggle_background is ON

    def toggle_live_img_process(self, state):
        self.logger.info('Turning Live Image Processing ' + ['off', 'on'][state])
        self.experiment.toggle_live_image_processing_method(state)
        self.actionToggle_bg_reduction.setEnabled(not state)  # disable toggle_background while toggle_live_img_process is ON

    def toggle_saving(self, state):
        if state:
            self.experiment.save_stream()
            self.actionStart_Continuous_Saves.setToolTip('Stop Saving')
        else:
            self.experiment.stop_save_stream()
            self.actionStart_Continuous_Saves.setToolTip('Start Saving')
            self.actionStart_Continuous_Saves.setChecked(False)

    def set_roi(self):
        self.refresh_timer.stop()
        X, Y = self.camera_viewer_widget.get_roi_values()
        self.experiment.set_roi(X, Y)
        X, Y = self.experiment.camera.get_roi()
        self.camera_viewer_widget.set_roi_lines((X[0],X[1]+1), (Y[0], Y[1]+1))
        self.refresh_timer.start()

    def clear_roi(self):
        self.refresh_timer.stop()
        self.experiment.clear_roi()
        self.camera_viewer_widget.set_roi_lines([0, self.experiment.max_width], [0, self.experiment.max_height])
        self.refresh_timer.start()

    def save_image(self):
        self.experiment.save_image()

    def start_tracking(self):
        self.experiment.start_tracking()
        # self.tracking = True

    def start_saving_tracks(self):
        self.experiment.start_saving_location()

    def stop_saving_tracks(self):
        self.experiment.stop_saving_location()

    def start_linking(self):
        if self.experiment.link_particles_running:
            self.stop_linking()
            return
        self.experiment.start_linking_locations()
        self.actionStart_Linking.setToolTip('Stop Linking')

    def stop_linking(self):
        self.experiment.stop_linking_locations()
        self.actionStart_Linking.setToolTip('Start Linking')

    def calculate_histogram(self):
        if not self.experiment.location.calculating_histograms:
            self.experiment.location.calculate_histogram()

    def update_histogram(self, values):
        pass
        # if len(values) > 0:
            # vals = np.array(values)[:, 0]
            # vals = vals[~np.isnan(vals)]
            # self.analysis_dock_widget.histogram_widget.update_distribution(vals)

    def update_tracks(self):
        pass
        # locations = self.experiment.location.relevant_tracks()
        # self.analysis_dock_widget.tracks_widget.plot_trajectories(locations)

    def update_tracking_config(self, config):
        config = dict(
            tracking=config
        )
        self.experiment.update_config(**config)

    def update_config(self, config):
        self.experiment.update_config(**config)

    def closeEvent(self, *args, **kwargs):
        self.experiment.finalize()
        #time.sleep(1)
        super().closeEvent(*args, **kwargs)
