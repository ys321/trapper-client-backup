import datetime
import os
import platform
import sys
import subprocess
import tempfile
from threading import Thread
import webbrowser

import pytz
import requests
from pandas import DataFrame
from PIL import Image

# Temporary fix for Windows
# https://github.com/kivy/kivy/pull/7299
if platform.system() == "Windows":
    try:
        from ctypes import windll, c_int64

        windll.user32.SetProcessDpiAwarenessContext(c_int64(-4))
    except ImportError:
        pass

# Kivy imports
from kivy.app import App
from kivy.clock import mainthread
from kivy.config import Config

# Sets some kivy configurations before creating main window
Config.set("kivy", "desktop", 1)
Config.set("kivy", "exit_on_escape", False)
Config.set("graphics", "resizable", True)
Config.set("graphics", "window_state", "maximized")
Config.set("graphics", "height", 1000)
Config.set("graphics", "width", 1500)
Config.set("input", "mouse", "mouse, disable_multitouch")

from kivy.properties import (
    StringProperty,
    ObjectProperty,
    BooleanProperty,
    NumericProperty,
)
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.popup import Popup
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.progressbar import ProgressBar
from kivy.storage.jsonstore import JsonStore
import kivy.resources
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivy.uix.recycleboxlayout import RecycleBoxLayout
from kivy.uix.behaviors import FocusBehavior
from kivy.uix.recycleview.layout import LayoutSelectionBehavior
from kivy.uix.settings import SettingsWithTabbedPanel

from kivy.garden.filebrowser import FileBrowser

# trapper-client imports
from ftp import FTPClient
from convert import MediaConverter
from package import DataPackageGenerator, localize_ignore_dst
from trapper_con import TrapperConnection

# Force creation of main window
# EventLoop.ensure_window()


### ---------------------------------------------------------- ###
### CONFIG
### ---------------------------------------------------------- ###

DATA_ROOT = os.path.join(os.path.abspath(os.path.dirname(__file__)), "data")
SETTINGS_SAVED = [
    "trapper_host",
    "trapper_login",
    "trapper_pass",
    "rproject_name",
    "rproject_acronym",
    "rproject_id",
    "timezone",
    "timezone_ignore_dst",
    "username",
    "ffmpeg_path",
]
DEFAULT_SRC_EXT_IMAGES = [".jpg", ".jpeg", ".png", ".gif"]
DEFAULT_SRC_EXT_VIDEOS = [".avi", ".mp4", ".webm", ".m4v"]

# set working directory
os.chdir(os.path.dirname(os.path.realpath(sys.argv[0])))

### ---------------------------------------------------------- ###
### HELPER WIDGETS
### ---------------------------------------------------------- ###


class InfoPopup(Popup):
    message = StringProperty("")

    def __init__(self, message, **kwargs):
        self.message = message
        super().__init__(**kwargs)


class LoadingPopup(Popup):
    pass


class InfoPopupFileContent(Popup):
    file_content = StringProperty("")
    message = StringProperty("")

    def __init__(self, filepath, message, **kwargs):
        super().__init__(**kwargs)
        try:
            self.message = message
            with open(filepath, "r") as f:
                self.file_content = f.read()
                f.close()
        except Exception as e:
            self.message = str(e)


class LabelTrapperCon(BoxLayout):
    TEXT_CONNECTED = "[color=#008000]CONNECTED![/color]"
    TEXT_NONCONNECTED = "[color=ff3333]NOT CONNECTED[/color]"

    image_path = StringProperty("")
    text = StringProperty(TEXT_NONCONNECTED)
    trapper_loggedin = BooleanProperty(False)

    def on_trapper_loggedin(self, instance, value):
        if value:
            self.text = self.TEXT_CONNECTED
        else:
            self.text = self.TEXT_NONCONNECTED


class Filechooser(FloatLayout):
    popup_title = StringProperty("")
    target_inst = ObjectProperty(None)
    target_attr = StringProperty("")
    last_location = StringProperty("")

    def __init__(
        self, target_inst, target_attr, title, last_location="", dirs_only=True
    ):
        super().__init__()
        self.target_attr = target_attr
        self.target_inst = target_inst
        self.popup_title = title
        if dirs_only:
            self.filters = [
                self.is_dir,
            ]
        else:
            self.filters = []

        ll_attr = getattr(self.target_inst, self.target_attr)
        ll_last = last_location
        last_location = ll_attr or ll_last or os.curdir
        if os.path.exists(last_location):
            self.last_location = last_location
        else:
            self.last_location = os.curdir

        self.fbrowser = FileBrowser(
            dirselect=True, path=self.last_location, filters=self.filters
        )
        self.fbrowser.bind(on_success=self.success, on_canceled=self.cancel)

    def cancel(self, instance):
        self.popup.dismiss()

    def success(self, instance):
        try:
            sel = str(instance.selection[0])
            if sel:
                setattr(self.target_inst, self.target_attr, sel)
                self.target_inst.manager.filechooser_last = sel
        except (IndexError, ValueError):
            pass
        self.popup.dismiss()

    def show(self):
        self.popup = Popup(
            title=self.popup_title,
            content=self.fbrowser,
            size_hint=(0.9, 0.9),
            auto_dismiss=False,
        )
        self.popup.open()

    def is_dir(self, directory, filename):
        return os.path.isdir(os.path.join(directory, filename))


class SelectableLabel(RecycleDataViewBehavior, Label):
    index = None
    selected = BooleanProperty(False)
    selectable = BooleanProperty(True)

    def refresh_view_attrs(self, rv, index, data):
        self.index = index
        return super().refresh_view_attrs(rv, index, data)

    def on_touch_down(self, touch):
        if super().on_touch_down(touch):
            return True
        if self.collide_point(*touch.pos) and self.selectable:
            return self.parent.select_with_touch(self.index, touch)

    def apply_selection(self, rv, index, is_selected):
        self.selected = is_selected
        if is_selected:
            rv.data[index]["selected"] = 1
        else:
            rv.data[index]["selected"] = 0


class SelectableRecycleBoxLayout(
    FocusBehavior, LayoutSelectionBehavior, RecycleBoxLayout
):
    pass


### ---------------------------------------------------------- ###
### THE SCREEN MANAGER
### ---------------------------------------------------------- ###


class Menu(BoxLayout):
    manager = ObjectProperty(None)


class TrapperClientScreenManager(ScreenManager):
    """ """

    _blue = "37abc8ff"
    _red = "ff3333"
    _green = "#008000"
    filechooser_last = StringProperty()

    # screens
    screen_main = ObjectProperty(None)
    screen_settings = ObjectProperty(None)
    screen_convert = ObjectProperty(None)
    screen_package = ObjectProperty(None)

    # ftp
    ftp_host = StringProperty("")
    ftp_login = StringProperty("")
    ftp_pass = StringProperty("")

    # trapper
    trapper_host = StringProperty("")
    trapper_login = StringProperty("")
    trapper_pass = StringProperty("")

    timezone = StringProperty("")
    timezone_ignore_dst = BooleanProperty(False)
    username = StringProperty("")
    rproject_name = StringProperty("")
    rproject_acronym = StringProperty("")
    rproject_id = None
    ffmpeg_path = StringProperty("")
    data_dir = None
    store = None
    popup = None
    # FTP connection
    ftp_con = None
    # Trapper connection
    trapper_con = None
    trapper_loggedin = BooleanProperty(False)
    tmpdir = ""

    # continue with packaging after media conversion
    convert_continue = False
    convert_continue_media_root = ""

    # continue with uploading after data package generation
    upload_continue = False
    upload_continue_package_zip = ""
    upload_continue_package_yaml = ""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.app = App.get_running_app()

        # initiate storage
        self.data_dir = self.get_user_data_path()
        self.store = JsonStore(os.path.join(self.data_dir, "storage.json"))

        # update settings
        self.update_settings()

        # get ftp credentials
        self.get_ftp_credentials()

    def get_user_data_path(self):
        return DATA_ROOT

    def update_settings(self):
        try:
            settings_dict = self.store.get("settings")["settings"]
            for s in SETTINGS_SAVED:
                try:
                    setattr(self, s, settings_dict[s])
                except KeyError:
                    setattr(self, s, "")
        except KeyError:
            pass

    def login2trapper(self, host=None, login=None, password=None):
        # get global configs
        verify_ssl = bool(int(self.app.config.get("trapper-client", "verify_ssl")))
        # set credentials
        if host is None:
            host = self.trapper_host
        if login is None:
            login = self.trapper_login
        if password is None:
            password = self.trapper_pass
        self.trapper_con = TrapperConnection(host)
        try:
            r = self.trapper_con.test_login(login, password, verify=verify_ssl)
            if r == "0":
                self.trapper_loggedin = True
                msg = (
                    "You have successfully logged in to:\n" "[color={c}]{url}[/color]"
                ).format(c=self._blue, url=self.trapper_host)
            else:
                self.trapper_loggedin = False
                msg = (
                    "Login failed. Please check your settings. "
                    "Login URL: [color={c}]{url}[/color]\n"
                ).format(c=self._blue, url=self.trapper_con.login_url)
        except requests.exceptions.RequestException as e:
            self.trapper_loggedin = False
            msg = str(e)
        self.show_info_popup(msg)

    def get_ftp_credentials(self):
        self.ftp_host = self.app.config.get("trapper-client", "ftp_host")
        if not self.ftp_host and self.trapper_host:
            self.ftp_host = self.trapper_host.split("//", 1)[1]
        self.ftp_login = self.app.config.get("trapper-client", "ftp_login")
        if not self.ftp_login and self.trapper_login:
            self.ftp_login = self.trapper_login.split("@")[0]
        self.ftp_pass = self.app.config.get("trapper-client", "ftp_pass")
        if not self.ftp_pass and self.trapper_pass:
            self.ftp_pass = self.trapper_pass

    @mainthread
    def show_info_popup(self, msg):
        if self.popup:
            self.popup.dismiss()
            self.popup = None
        self.popup = InfoPopup(msg)
        self.popup.open()

    @mainthread
    def show_loading_popup(self, title):
        if self.popup:
            self.popup.dismiss()
            self.popup = None
        self.popup = LoadingPopup(title=title)
        self.popup.open()

    @mainthread
    def show_file_content_popup(self, filepath, message, title="Info"):
        if self.popup:
            self.popup.dismiss()
            self.popup = None
        self.popup = InfoPopupFileContent(
            filepath=filepath, message=message, title=title
        )
        self.popup.open()

    def get_tmpdir(self, overwrite=False):
        if not os.path.isdir(self.tmpdir) or overwrite:
            self.tmpdir = tempfile.mkdtemp()
        return self.tmpdir

    def open_ref_in_browser(self, popup, link):
        webbrowser.open(link)

    def show_help(self):
        webbrowser.open("https://trapper-client.readthedocs.io/en/latest/overview.html")

    def show_download_ffmpeg(self):
        webbrowser.open("https://ffbinaries.com/downloads")


### ---------------------------------------------------------- ###
### THE MAIN SCREEN
### ---------------------------------------------------------- ###


class MainScreen(Screen):
    """ """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)


### ---------------------------------------------------------- ###
### THE SETTINGS SCREEN
### ---------------------------------------------------------- ###


class SettingsScreen(Screen):
    """ """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    @mainthread
    def on_enter(self):
        pass

    def save_settings(self, settings_dict):
        self.manager.show_loading_popup(title="Saving settings...")
        if self.validate_settings(settings_dict):
            settings_dict.update({"rproject_id": self.manager.rproject_id})
            self.manager.store.put("settings", settings=settings_dict)
            self.manager.update_settings()
            self.manager.show_info_popup("Your settings were successfully saved!")

    def validate_settings(self, settings_dict):
        try:
            timezone = settings_dict["timezone"]
            pytz.timezone(timezone)
        except (pytz.UnknownTimeZoneError, AttributeError):
            msg = (
                "You have to specify a correct timezone. See:\n"
                "https://en.wikipedia.org/wiki/List_of_tz_database_time_zones"
            )
            self.manager.show_info_popup(msg)
            return False
        acronym = settings_dict["rproject_acronym"]
        if acronym and self.manager.rproject_id is None:
            msg = (
                "Please, verify your project first by clicking\n"
                'the button: "Check & set as active"'
            )
            self.manager.show_info_popup(msg)
            return False
        return True

    def thread_check_ffmpeg(self, ffmpeg_path):
        self.manager.show_loading_popup(title="Checking FFMPEG...")
        self.check_ffmpeg(ffmpeg_path)

    def check_ffmpeg(self, ffmpeg_path):
        try:
            p = subprocess.Popen(
                [ffmpeg_path, "-h"], stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            output, error = p.communicate()
            msg = "FFMPEG available:\n[color={c}]{e}[/color]".format(
                c=self.manager._blue, e=error.split(b"\n")[0].decode("utf-8")
            )
        except Exception as e:
            msg = str(e)
        self.manager.show_info_popup(msg)

    def thread_check_rproject(self, acronym):
        self.manager.show_loading_popup(title="Checking project...")
        Thread(target=self.check_rproject, args=(acronym,)).start()

    def check_rproject(self, acronym):
        if self.manager.trapper_loggedin:
            if not acronym:
                msg = "Please, provide the project's acronym."
                self.manager.show_info_popup(msg)
                return
            qstr = "acronym={}".format(acronym)
            r = self.manager.trapper_con.get_rprojects(
                qstr, roles=["Admin", "Collaborator"]
            )
            if r:
                msg = "Project successfully verified!"
                self.manager.rproject_acronym = acronym
                self.manager.rproject_id = r[0]["pk"]
            else:
                msg = (
                    "There is no project [color={c}]{a}[/color] or you have "
                    "no access to it."
                ).format(c=self.manager._blue, a=acronym)
            self.manager.show_info_popup(msg)
            return
        msg = "You are not connected to the Trapper server."
        self.manager.show_info_popup(msg)

    def thread_ftp_con(self):
        self.manager.show_loading_popup(title="Testing FTP connection...")
        Thread(target=self.test_ftp_con, args=()).start()

    def test_ftp_con(self):
        self.manager.get_ftp_credentials()
        ftp_tls = bool(int(self.manager.app.config.get("trapper-client", "ftp_tls")))
        ftp_passive = bool(
            int(self.manager.app.config.get("trapper-client", "ftp_passive"))
        )
        self.manager.ftp_con = None
        print("FTP TLS: ", ftp_tls)
        try:
            ftp = FTPClient(
                self.manager.ftp_host,
                self.manager.ftp_login,
                self.manager.ftp_pass,
                passive=ftp_passive,
                tls=ftp_tls,
            )
            if ftp.connect():
                self.manager.ftp_con = ftp
                msg = "FTP connection successfull!"
            else:
                msg = "No FTP connection. Please, check your settings."
        except Exception:
            msg = "No FTP connection. Please, check your settings."
        self.manager.show_info_popup(msg)

    def thread_trapper_con(self, host, login, password):
        self.manager.show_loading_popup(title="Connecting to Trapper...")
        Thread(target=self.manager.login2trapper, args=(host, login, password)).start()


### ---------------------------------------------------------- ###
### THE CONVERT SCREEN
### ---------------------------------------------------------- ###


class ConvertScreen(Screen):
    """ """

    media_root = StringProperty("")
    output_path = StringProperty("")
    resize_img = BooleanProperty()
    resize_img_size_x = NumericProperty(800)
    resize_img_size_y = NumericProperty(600)
    convert2mp4 = BooleanProperty()
    convert2webm = BooleanProperty()
    overwrite = BooleanProperty(False)
    # RecycleView instance
    img_src_ext = None
    # RecycleView instance
    vid_src_ext = None
    progress_msg = StringProperty("")
    media_converter = None
    btn_continue = None
    stop_thread_convert_flag = False
    conversion_inprogress = False
    pbar = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    @mainthread
    def on_enter(self):
        # get global configs
        image_ext = self.manager.app.config.get("trapper-client", "image_ext").split(
            ","
        )
        video_ext = self.manager.app.config.get("trapper-client", "video_ext").split(
            ","
        )

        self.img_src_ext.data = [{"text": str(x)} for x in image_ext]
        self.vid_src_ext.data = [{"text": str(x)} for x in video_ext]

    def show_filechooser(self, target_attr, title):
        self.fch = Filechooser(self, target_attr, title, self.manager.filechooser_last)
        self.fch.show()

    def get_selected_images_ext(self):
        sel = [k["text"] for k in self.img_src_ext.data if k["selected"]]
        return sel

    def get_selected_videos_ext(self):
        sel = [k["text"] for k in self.vid_src_ext.data if k["selected"]]
        return sel

    def progress_callback(self, i, fname):
        self.pbar.value += 1
        self.progress_msg = "{}/{}\n{}".format(
            int(self.pbar.value), self.pbar.max, fname
        )
        if self.stop_thread_convert_flag:
            self.stop_thread_convert_flag = False
            raise Exception("The conversion of your media files has been stopped.")

    def thread_convert(self):
        try:
            self.conversion_inprogress = True
            self.media_converter.handle()
            msg = (
                "Your media were successfully converted!\n"
                "You will find your converted media at:\n{}"
            ).format(self.ids.output_path.text.replace("\\", "/"))
            self.add_continue_button()

        except Exception as e:
            msg = str(e)

        self.progress_msg = ""
        self.manager.show_info_popup(msg)
        self.conversion_inprogress = False

    @mainthread
    def add_continue_button(self):
        # Replace progress bar with continue button
        self.btn_continue = Button(
            text="Continue and make your data package!",
            font_size=18,
            background_color=(0.0, 0.9, 0.1, 0.5),
        )
        self.btn_continue.bind(on_release=self.move2package_screen)
        self.ids.progress_bar.clear_widgets()
        self.ids.progress_bar.add_widget(self.btn_continue)

    def move2package_screen(self, *args):
        self.manager.convert_continue = True
        self.manager.convert_continue_media_root = self.output_path
        self.ids.progress_bar.clear_widgets()
        self.manager.current = "package"

    def run(self):
        if self.btn_continue is not None:
            self.ids.progress_bar.clear_widgets()
            self.btn_continue = None
        try:
            self.media_converter = MediaConverter(
                media_root=self.media_root,
                output_path=self.output_path,
                resize_img=self.resize_img.active,
                resize_img_size=(
                    int(self.ids.resize_img_size_x.text),
                    int(self.ids.resize_img_size_y.text),
                ),
                convert2mp4=self.convert2mp4.active,
                convert2webm=self.convert2webm.active,
                src_ext_images=self.get_selected_images_ext(),
                src_ext_videos=self.get_selected_videos_ext(),
                ffmpeg=self.manager.ffmpeg_path,
                keep_mdt=True,
                overwrite=self.overwrite.active,
                callback=self.progress_callback,
            )
            self.pbar = ProgressBar(max=self.media_converter.nfiles)
            self.ids.progress_bar.add_widget(self.pbar)
            Thread(target=self.thread_convert, args=()).start()

        except Exception as e:
            self.ids.progress_bar.clear_widgets()
            self.manager.show_info_popup(str(e))

    def stop_thread_convert(self):
        if not self.conversion_inprogress:
            msg = "The conversion is not running at the moment."
            self.manager.show_info_popup(msg)
            return
        self.manager.show_loading_popup("Stopping the conversion..")
        self.ids.progress_bar.clear_widgets()
        self.stop_thread_convert_flag = True


### ---------------------------------------------------------- ###
### THE PACKAGE SCREEN
### ---------------------------------------------------------- ###


class PackageScreen(Screen):
    """
    The expected structure of multimedia files and sub-directories
    int the `media_root` directory:

    |- collection_name_1
    |   |- deploymentID_1
    |      |- filename_1
    |      |- filename_2
    |      |- filename_3
    |      |- filename_4
    |   |- deploymentID_2
    |      |- filename_1
    |      |- filename_2
    |      |- filename_3
    |      |- filename_4
    |   |- ...
    |- collection_name_2
    |   |- deploymentID_3
    |      |- ...
    |   |- ...
    |- ...
    """

    media_root = StringProperty("")
    output_path = StringProperty("")
    package_name = StringProperty("")
    timezone = None
    username = None
    rproject_id = None
    # RecycleView instance
    collections = None
    # RecycleView instance
    img_ext = None
    # RecycleView instance
    vid_ext = None
    progress_msg = StringProperty("")
    delete_collections = BooleanProperty(False)
    validated = False
    trapper_deployments = None
    btn_continue = None
    package_gen = None
    pbar = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def get_sub_dirs(self, root_dir):
        try:
            return next(os.walk(root_dir))[1]
        except Exception:
            return []

    def on_media_root(self, instance, value):
        collections_dirs = self.get_sub_dirs(value)
        self.collections.data = [
            {"text": str(x), "selected": 0} for x in collections_dirs
        ]

    def check_trapper_connection(self):
        if not self.manager.trapper_loggedin:
            msg = (
                "You are not logged in to Trapper.\n"
                "Please check your settings and connect to Trapper."
            )
            self.manager.show_info_popup(msg)
            return False
        return True

    def check_project(self):
        if not self.manager.rproject_id:
            msg = (
                "You have not set & verified your project yet.\n"
                "Please check your settings."
            )
            self.manager.show_info_popup(msg)
            return False
        return True

    @mainthread
    def on_enter(self):
        if self.manager.convert_continue:
            self.media_root = self.manager.convert_continue_media_root
        self.rproject_id = self.manager.rproject_id
        self.rproject_acronym = self.manager.rproject_acronym
        try:
            self.timezone = pytz.timezone(self.manager.timezone)
        except pytz.UnknownTimeZoneError:
            pass
        self.timezone_ignore_dst = self.manager.timezone_ignore_dst
        self.username = self.manager.trapper_login.split("@")[0]

        # get global configs
        image_ext = self.manager.app.config.get("trapper-client", "image_ext").split(
            ","
        )
        video_ext = self.manager.app.config.get("trapper-client", "video_ext").split(
            ","
        )
        self.img_ext.data = [{"text": str(x), "selected": 0} for x in image_ext]
        self.vid_ext.data = [{"text": str(x), "selected": 0} for x in video_ext]
        collections_dirs = self.get_sub_dirs(self.media_root)
        self.collections.data = [
            {"text": str(x), "selected": 0} for x in collections_dirs
        ]

    def show_filechooser(self, target_attr, title):
        self.fch = Filechooser(self, target_attr, title, self.manager.filechooser_last)
        self.fch.show()

    def get_selected_images_ext(self):
        sel = [k["text"] for k in self.img_ext.data if k["selected"]]
        return sel

    def get_selected_videos_ext(self):
        sel = [k["text"] for k in self.vid_ext.data if k["selected"]]
        return sel

    def get_selected_collections(self):
        sel = [k["text"] for k in self.collections.data if k["selected"]]
        return sel

    def get_deployments(self):
        qstr = "?research_project={}".format(self.manager.rproject_id)
        df = self.manager.trapper_con.get_deployments(query_str=qstr)
        self.trapper_deployments = df

    def progress_callback(self, i, fname):
        self.pbar.value += 1
        self.progress_msg = "{}/{}\n{}".format(
            int(self.pbar.value), self.pbar.max, fname
        )

    def package_generator_init(self):
        # first check connections
        if not self.check_trapper_connection():
            return
        if not self.check_project():
            return

        # get selected collections
        collections_sel = self.get_selected_collections()
        if len(collections_sel) == 0:
            msg = "You have to select at least one collection."
            self.manager.show_info_popup(msg)
            self.validated = False
            return False

        # then try to initiate DataPackageGenerator instance
        try:
            self.package_gen = DataPackageGenerator(
                data_path=self.media_root,
                output_path=self.output_path,
                collections=collections_sel,
                username=self.username,
                timezone=self.timezone,
                timezone_ignore_dst=self.timezone_ignore_dst,
                project=self.rproject_acronym,
                image_ext=self.get_selected_images_ext(),
                video_ext=self.get_selected_videos_ext(),
                callback=self.progress_callback,
                package_name_prefix=self.package_name,
            )
            return True

        except Exception as e:
            self.manager.show_info_popup(str(e))
            return False

    def thread_get_deployments_csv_template(self):
        Thread(target=self.get_deployments_csv_template, args=()).start()

    def get_deployments_csv_template(self):
        if not self.package_generator_init():
            return

        self.progress_msg = 'Generating "deployments_metadata.csv" template ...'
        outfile = os.path.join(self.output_path, "deploments_metadata.csv")
        data = {
            "deploymentID": [],
            "locationID": [],
            "start": [],
            "end": [],
        }
        selected_images_ext = self.get_selected_images_ext()
        selected_videos_ext = self.get_selected_videos_ext()

        for col in self.package_gen.collections:
            for root, dirnames, filenames in os.walk(
                os.path.join(self.media_root, col)
            ):
                if os.path.basename(root) == col or not filenames:
                    continue

                rdates = []
                for filename in filenames:
                    file_path = os.path.join(root, filename)
                    file_ext = os.path.splitext(filename)[1].lower()
                    if file_ext in selected_images_ext:
                        try:
                            rdate = Image.open(file_path)._getexif()[36867]
                            rdate = datetime.datetime.strptime(
                                rdate, "%Y:%m:%d %H:%M:%S"
                            )
                        except Exception:
                            rdate = datetime.datetime.fromtimestamp(
                                os.path.getmtime(file_path)
                            )
                    elif file_ext in selected_videos_ext:
                        rdate = datetime.datetime.fromtimestamp(
                            os.path.getmtime(file_path)
                        )
                    else:
                        continue
                    # make datetime object timezone aware
                    if self.timezone_ignore_dst:
                        rdate = localize_ignore_dst(rdate, self.timezone)
                    else:
                        rdate = self.timezone.localize(rdate)
                    rdates.append(rdate)

                if not rdates:
                    continue

                data["start"].append(min(rdates))
                data["end"].append(max(rdates))

                dep_id = os.path.basename(root)
                data["deploymentID"].append(dep_id)
                try:
                    loc_id = dep_id.split("-", 1)[1]
                except (ValueError, IndexError):
                    loc_id = ""
                data["locationID"].append(loc_id)

        df = DataFrame(
            data,
            columns=["deploymentID", "locationID", "start", "end"],
        )
        # convert "start" & "end" to a proper datetime format
        dt_format = "%Y-%m-%dT%H:%M:%S%z"
        df["start"] = df.start.dt.strftime(dt_format)
        df["end"] = df.end.dt.strftime(dt_format)

        # export to CSV
        df.to_csv(outfile, index=False)
        msg = (
            "The template was successfully generated! You can find it here:\n"
            "[color={c}]{outfile}[/color]"
        ).format(outfile=outfile.replace("\\", "/"), c=self.manager._blue)
        self.progress_msg = ""
        self.manager.show_info_popup(msg)
        return

    def thread_validate(self):
        self.manager.show_loading_popup(title="Validating your data structure...")
        Thread(target=self.validate, args=()).start()

    def validate(self):
        if not self.package_generator_init():
            return

        # get deployments
        self.get_deployments()
        trapper_deps = self.trapper_deployments.deploymentID.tolist()
        # compare local vs Trapper's deployments
        errors = []
        # iterate over collections
        for col in self.package_gen.collections:
            local_deps = self.get_sub_dirs(os.path.join(self.media_root, col))
            if len(local_deps) == 0:
                msg = (
                    "Error. The collection [color={c}]{col}[/color] does not "
                    "contain any deployments.".format(c=self.manager._blue, col=col)
                )
                self.manager.show_info_popup(msg)
                self.validated = False
                return 1
            errors_list = [k for k in local_deps if k not in trapper_deps]
            errors.extend(list(zip([col] * len(errors_list), errors_list)))
        if len(errors) > 0:
            log_path = os.path.join(self.output_path, "missing_deployments.csv")
            df_errors = DataFrame(errors, columns=["collection", "deploymentID"])
            df_errors.to_csv(log_path, sep="\t", index=False)
            msg = (
                "Some of your deployments are not recognized by Trapper. "
                "Please, check the logfile below and try again.\n"
                "[color={c}]{fp}[/color]".format(
                    c=self.manager._blue, fp=log_path.replace("\\", "/")
                )
            )
            self.manager.show_file_content_popup(
                filepath=log_path, message=msg, title="Missing deployments"
            )
            self.validated = False
            return 1
        else:
            msg = "Your data structure was successfully validated!"
            self.manager.show_info_popup(msg)
            self.validated = True
            return 0

    def move2upload_screen(self, *args):
        self.manager.upload_continue = True
        self.manager.upload_continue_package_zip = self.package_gen.zip_path
        self.manager.upload_continue_package_yaml = self.package_gen.yaml_path
        self.package_gen = None
        self.ids.progress_bar.clear_widgets()
        self.manager.current = "upload"

    @mainthread
    def add_continue_button(self):
        # Replace progress bar with continue button
        self.btn_continue = Button(
            text="Continue and upload your package to Trapper!",
            font_size=18,
            background_color=(0.0, 0.9, 0.1, 0.5),
        )
        self.btn_continue.bind(on_release=self.move2upload_screen)
        self.ids.progress_bar.clear_widgets()
        self.ids.progress_bar.add_widget(self.btn_continue)

    def thread_package(self):
        try:
            self.package_gen.run()
            msg = (
                "Your data package was successfully generated!\n"
                "You will find it at:\n{}"
            ).format(self.ids.output_path.text.replace("\\", "/"))

            self.add_continue_button()

        except Exception as e:
            msg = str(e)

        self.progress_msg = ""
        self.manager.show_info_popup(msg)
        self.validated = False

    def run(self):
        if not self.validated:
            msg = "Please, first validate your input data."
            self.manager.show_info_popup(msg)
            return

        if self.btn_continue is not None:
            self.ids.progress_bar.clear_widgets()
            self.btn_continue = None

        self.pbar = ProgressBar(max=len(self.package_gen.yaml_generator.files))
        self.ids.progress_bar.add_widget(self.pbar)

        Thread(target=self.thread_package, args=()).start()


### ---------------------------------------------------------- ###
### THE UPLOAD SCREEN
### ---------------------------------------------------------- ###


class UploadScreen(Screen):
    data_package_zip = StringProperty("")
    data_package_yaml = StringProperty("")
    trigger_processing = BooleanProperty(True)
    trigger_processing_remove_zip = BooleanProperty(False)
    progress_msg = StringProperty("")
    blocksize = 8192
    uploaded_file = ""
    stop_thread_upload_flag = ""
    upload_inprogress = False
    pbar = None

    @mainthread
    def on_enter(self):
        self.manager.get_ftp_credentials()
        if self.manager.upload_continue:
            self.data_package_zip = self.manager.upload_continue_package_zip
            self.data_package_yaml = self.manager.upload_continue_package_yaml

    def show_filechooser(self, target_attr, title):
        self.fch = Filechooser(
            self, target_attr, title, self.manager.filechooser_last, dirs_only=False
        )
        self.fch.show()

    def thread_trigger_processing(self):
        data = {
            "yaml_file": os.path.basename(self.data_package_yaml),
            "zip_file": os.path.basename(self.data_package_zip),
            "remove_zip": self.ids.trigger_processing_remove_zip.active,
        }
        response = self.manager.trapper_con.collection_process(data)
        if response.status_code == 200:
            msg = (
                "Your data package has been successfully uploaded and is being "
                "processed by Trapper now!"
            )
        else:
            try:
                resp_data = response.json().get("data", {})
            except requests.exceptions.JSONDecodeError:
                resp_data = {}
            resp_msg = resp_data.get("message", "TRAPPER API did not respond.")
            resp_err = resp_data.get("errors", "")
            msg = (
                "Your data package has been successfully uploaded but could not "
                "be automatically processed by Trapper. See the reason below:\n"
                f"Response status: {response.status_code}\n"
                f"{resp_msg}\n"
                f"{resp_err}\n"
            )
        self.manager.show_info_popup(msg)

    @mainthread
    def add_progress_bar(self, fp_size):
        self.pbar = ProgressBar(max=fp_size)
        self.ids.progress_bar.add_widget(self.pbar)

    @mainthread
    def remove_progress_bar(self):
        self.ids.progress_bar.clear_widgets()

    def progress_callback(self, *args):
        self.pbar.value += self.blocksize
        self.progress_msg = "{}/{}\n{}".format(
            int(self.pbar.value), self.pbar.max, self.uploaded_file
        )
        if self.stop_thread_upload_flag:
            # TODO: improve this experimental code
            self.stop_thread_upload_flag = False
            try:
                self.manager.ftp_con.close_connection()
            except Exception:
                pass
            self.manager.ftp_con.connect()
            raise Exception("The upload of your data has been stopped.")

    def thread_upload(self, resume, files2upload):
        self.progress_msg = "Connecting to FTP server.."
        self.manager.ftp_con.connect()

        for fp in files2upload:
            self.uploaded_file = fp
            fp_size = os.path.getsize(fp)

            # start progress bar
            self.add_progress_bar(fp_size)

            # do we want to resume a previous upload?
            rest_pos = None
            if resume:
                try:
                    self.manager.ftp_con.set_ftp_directory("/collections")
                    rest_pos = self.manager.ftp_con.ftp.size(os.path.basename(fp))
                    if rest_pos is None:
                        raise Exception()
                except Exception:
                    msg = (
                        "Can not resume a previous upload. "
                        "There is no such a file on the FTP server."
                    )
                    self.manager.show_info_popup(msg)
                    self.remove_progress_bar()
                    self.progress_msg = ""
                    return
                self.pbar.value = rest_pos

            # if we have working FTP connection try to upload a package
            try:
                self.manager.ftp_con.set_ftp_directory("/collections")
                self.upload_inprogress = True
                self.manager.ftp_con.upload(
                    fp,  # filepath,
                    bsize=self.blocksize,
                    callback=self.progress_callback,
                    rest_pos=rest_pos,
                )
            except Exception as e:
                msg = str(e)
                self.manager.show_info_popup(msg)
                self.remove_progress_bar()
                self.progress_msg = ""
                self.upload_inprogress = False
                return

            self.progress_msg = ""
            self.remove_progress_bar()

        self.manager.ftp_con.close_connection()
        self.upload_inprogress = False

        if self.ids.trigger_processing.active:
            # start trigger processing thread
            Thread(target=self.thread_trigger_processing).start()
        else:
            msg = "Your data package has been successfully uploaded to Trapper!"
            self.manager.show_info_popup(msg)

    def upload(self, resume=False):
        # first check FTP connection
        if self.manager.ftp_con is None:
            msg = (
                "You have not set up & verified your FTP connection.\n"
                "Please check your settings."
            )
            self.manager.show_info_popup(msg)
            return

        files2upload = [k for k in [self.data_package_yaml, self.data_package_zip] if k]

        if not files2upload:
            msg = "There are no files to upload."
            self.manager.show_info_popup(msg)
            self.progress_msg = ""
            return

        # Check provided file paths
        for fp in files2upload:
            if not os.path.isfile(fp):
                msg = f"There is no file {fp}."
                self.manager.show_info_popup(msg)
                self.progress_msg = ""
                return

        # start upload thread
        Thread(target=self.thread_upload, args=(resume, files2upload)).start()

    def stop_thread_upload(self):
        if not self.upload_inprogress:
            msg = "Nothing is uploading at the moment."
            self.manager.show_info_popup(msg)
            return
        self.stop_thread_upload_flag = True
        self.manager.show_loading_popup("Stopping the upload..")


### ---------------------------------------------------------- ###
### RUN APP
### ---------------------------------------------------------- ###


class TrapperApp(App):
    """ """

    def build(self):
        self.settings_cls = SettingsWithTabbedPanel
        return Menu()

    def build_config(self, config):
        """
        Set the default values for the configs sections.
        """
        config.setdefaults(
            "trapper-client",
            {
                "verify_ssl": 1,
                "ftp_tls": 1,
                "ftp_passive": 1,
                "ftp_host": "",
                "ftp_login": "",
                "ftp_pass": "",
                "image_ext": ",".join(DEFAULT_SRC_EXT_IMAGES),
                "video_ext": ",".join(DEFAULT_SRC_EXT_VIDEOS),
            },
        )

    def build_settings(self, settings):
        """
        Add our custom section to the default configuration object.
        """
        settings.add_json_panel("trapper-client", self.config, "app_settings.json")


def resourcePath():
    """
    Returns path containing content - either locally or in
    pyinstaller tmp file
    """
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS)

    return os.path.join(os.path.abspath("."))


if __name__ == "__main__":
    kivy.resources.resource_add_path(resourcePath())
    TrapperApp().run()
