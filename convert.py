import os
import datetime
import platform
import shutil
import subprocess
from PIL import Image


class MediaConverter:
    """ """

    DEFAULT_RESIZE_IMG_SIZE = (800, 600)

    def __init__(
        self,
        media_root,
        output_path,
        ffmpeg="ffmpeg",
        keep_mdt=True,
        resize_img=False,
        resize_img_size=None,
        convert2mp4=True,
        convert2webm=False,
        src_ext_images=None,
        src_ext_videos=None,
        overwrite=False,
        callback=None,
    ):
        if not media_root or not output_path:
            raise Exception('You have to choose both "Media root" and "Output path".')
        if not os.path.isdir(media_root):
            raise Exception("There is no directory: %s" % media_root)
        if not os.path.isdir(output_path):
            raise Exception("There is no directory: %s" % output_path)

        self.media_root = media_root
        self.output_path = output_path
        self.overwrite = overwrite
        self.FFMPEG = ffmpeg
        self.keep_mdt = keep_mdt
        self.callback = callback
        if (src_ext_images is None or len(src_ext_images) == 0) and (
            src_ext_videos is None or len(src_ext_videos) == 0
        ):
            raise Exception(
                "You have to provide at least one image or video extension."
            )
        self.src_ext_images = src_ext_images
        self.src_ext_videos = src_ext_videos
        self.resize_img = resize_img
        self.resize_img_size = resize_img_size
        if self.resize_img and self.resize_img_size is None:
            self.resize_img_size = self.DEFAULT_RESIZE_IMG_SIZE
        self.convert2mp4 = convert2mp4
        self.convert2webm = convert2webm

        # get matches
        self.matches_images = self.get_matches(self.src_ext_images)
        self.matches_videos = self.get_matches(self.src_ext_videos)
        self.nfiles = len(self.matches_images) + len(self.matches_videos)

        if self.nfiles == 0:
            raise Exception(
                (
                    'There is nothing to convert. Better check your "Media root" path '
                    "and selected image and video extensions."
                )
            )

    def replace_ext(self, filepath, ext):
        ext = ext.split(".")[-1]
        base = os.path.splitext(filepath)[0]
        return ".".join([base, ext])

    def filter_files(self, filenames, src_ext):
        return [k for k in filenames if os.path.splitext(k)[1].lower() in [*src_ext]]

    def get_matches(self, src_ext):
        matches = []
        for root, dirnames, filenames in os.walk(self.media_root):
            for filename in self.filter_files(filenames, src_ext):
                matches.append(os.path.join(root, filename).replace("\\", "/"))
        return matches

    def update_mdt(self, file_path_orig, file_path_conv):
        mdt_original = datetime.datetime.utcfromtimestamp(
            os.path.getmtime(file_path_orig)
        )
        timestamp = (mdt_original - datetime.datetime(1970, 1, 1)).total_seconds()
        os.utime(file_path_conv, (timestamp, timestamp))

    def get_outfile_path(self, outfile):
        outfile_path = os.path.join(
            self.output_path, os.path.relpath(outfile, self.media_root)
        ).replace("\\", "/")
        if not os.path.isdir(os.path.dirname(outfile_path)):
            os.makedirs(os.path.dirname(outfile_path))
        return outfile_path

    def handle(self, *args):
        i = 1

        # First do the job with images
        for image in self.matches_images:
            outfile = self.get_outfile_path(image)

            if self.callback:
                self.callback(i, image)
            i = i + 1

            if not os.path.isfile(outfile) or self.overwrite:
                img = Image.open(image)
                if self.resize_img:
                    # resize an image
                    img.thumbnail(self.resize_img_size, Image.ANTIALIAS)
                    # save it with original exif data
                    img.save(outfile, exif=img.info["exif"])
                else:
                    shutil.copy2(image, outfile)

            if self.keep_mdt:
                self.update_mdt(image, outfile)

        # Next do the job with videos
        for video in self.matches_videos:
            outfile = self.get_outfile_path(video)

            if self.callback:
                self.callback(i, video)
            i = i + 1

            if not (self.convert2mp4 or self.convert2webm):
                shutil.copy2(video, outfile)

            # "mp4" conversion
            if self.convert2mp4:
                outfile = self.replace_ext(outfile, "mp4")
                if not os.path.isfile(outfile) or self.overwrite:
                    ffmpeg_mp4 = [
                        f"{self.FFMPEG}",
                        "-y",
                        "-i",
                        "-",
                        "-preset",
                        "fast",
                        "-pix_fmt",
                        "yuv420p",
                        "-vcodec",
                        "libx264",
                        "-b:v",
                        "750k",
                        "-c:a",
                        "aac",
                        "-strict",
                        "-2",
                        "-ac",
                        "2",
                        "-movflags",
                        "faststart",
                        "-qmin",
                        "10",
                        "-qmax",
                        "42",
                        "-keyint_min",
                        "150",
                        "-g",
                        "150",
                        "-loglevel",
                        "error",
                        "-nostats",
                        f"{outfile}",
                    ]
                    with open(video, "rb") as _stream:
                        kwargs = {
                            "stdin": _stream.raw,
                            "stdout": subprocess.PIPE,
                            "stderr": subprocess.PIPE,
                        }
                        if platform.system() == "Windows":
                            kwargs.update(
                                creationflags=subprocess.CREATE_NO_WINDOW,
                            )
                        p = subprocess.Popen(ffmpeg_mp4, **kwargs)
                    stdout, stderr = p.communicate()

                    if self.keep_mdt:
                        self.update_mdt(video, outfile)

            # "webm" conversion
            if self.convert2webm:
                outfile = self.replace_ext(outfile, "webm")
                if not os.path.isfile(outfile) or self.overwrite:
                    ffmpeg_webm = [
                        f"{self.FFMPEG}",
                        "-y",
                        "-i",
                        "-",
                        "-codec:v",
                        "libvpx",
                        "-codec:a",
                        "vorbis",
                        "-strict",
                        "-2",
                        "-ac",
                        "2",
                        "-b:a",
                        "128k",
                        # -cpu-used => a critical parameter related
                        # to the speed of conversion
                        "-quality",
                        "good",
                        "-cpu-used",
                        "5",
                        "-qmin",
                        "0",
                        "-qmax",
                        "45",
                        "-keyint_min",
                        "150",
                        "-g",
                        "150",
                        "-loglevel",
                        "error",
                        "-nostats",
                        f"{outfile}",
                    ]
                    with open(video, "rb") as _stream:
                        kwargs = {
                            "stdin": _stream.raw,
                            "stdout": subprocess.PIPE,
                            "stderr": subprocess.PIPE,
                        }
                        if platform.system() == "Windows":
                            kwargs.update(
                                creationflags=subprocess.CREATE_NO_WINDOW,
                            )
                        p = subprocess.Popen(ffmpeg_webm, **kwargs)
                    stdout, stderr = p.communicate()

                    if self.keep_mdt:
                        self.update_mdt(video, outfile)
