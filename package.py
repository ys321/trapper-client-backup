"""
TODO: docstrings
"""
import os
import logging
import datetime
import zipfile
from collections import OrderedDict

import yaml
from PIL import Image
import pytz


# YAML mapping extension
_mapping_tag = yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG


def dict_representer(dumper, data):
    return dumper.represent_dict(data.items())


def dict_constructor(loader, node):
    return OrderedDict(loader.construct_pairs(node))


yaml.add_representer(OrderedDict, dict_representer)
yaml.add_constructor(_mapping_tag, dict_constructor)


# datetime localize function which ignores DST
def localize_ignore_dst(dt, zoneinfo):
    utc_offset = zoneinfo.utcoffset(dt)
    dst_offset = zoneinfo.dst(dt)
    standard_offset = utc_offset - dst_offset
    dt = dt.replace(tzinfo=datetime.timezone(standard_offset))
    return dt.astimezone(zoneinfo)


class YAMLDefinitionGenerator:
    """
    TODO: docstrings
    """

    def __init__(
        self,
        data_dir,
        collections,
        timezone,
        image_ext,
        video_ext,
        project_name,
        timezone_ignore_dst=False,
    ):
        self.data_dir = data_dir
        self.collections = collections
        self.timezone = timezone
        self.timezone_ignore_dst = timezone_ignore_dst
        self.image_ext = image_ext
        self.video_ext = video_ext
        self.all_ext = image_ext + video_ext
        self.project_name = project_name
        self.files = []
        self.data_dict = self.build_data_dict()

    def get_collection_def(self, name):
        collection_def = OrderedDict()
        collection_def["name"] = name
        collection_def["project_name"] = self.project_name
        collection_def["timezone"] = self.timezone.zone
        collection_def["timezone_ignore_dst"] = self.timezone_ignore_dst
        collection_def["resources_dir"] = name
        collection_def["deployments"] = []
        collection_def["resources"] = []
        return collection_def

    def get_deployment_def(self, deployment):
        deployment_def = OrderedDict()
        deployment_def["deployment_id"] = deployment
        deployment_def["resources"] = []
        return deployment_def

    def get_date_recorded(self, filepath):
        """
        The method to get datetime when resource was recorded under
        a simple assumption that this is a date of the last modification of
        recorded file. It returns UTC timestamp. In case of images it first
        tries to read 'DateTimeOriginal` EXIF tag.
        """
        if os.path.splitext(filepath)[1].lower() in self.image_ext:
            try:
                dt = Image.open(filepath)._getexif()[36867]
                dt = datetime.datetime.strptime(dt, "%Y:%m:%d %H:%M:%S")

            except Exception:
                dt = datetime.datetime.fromtimestamp(os.path.getmtime(filepath))
        else:
            dt = datetime.datetime.fromtimestamp(os.path.getmtime(filepath))
        # make datetime object timezone aware
        if self.timezone_ignore_dst:
            dt = localize_ignore_dst(dt, self.timezone)
        else:
            dt = self.timezone.localize(dt)
        # convert to UTC
        dt = dt.astimezone(pytz.utc)
        dt = datetime.datetime.strftime(dt, "%Y-%m-%dT%H:%M:%S%z")
        return dt

    def get_resource_def(self, resource, resources_level):
        filepath = os.path.join(resources_level, resource)
        split_name = os.path.splitext(resource)
        resource_def = OrderedDict()
        resource_def["name"] = split_name[0]
        resource_def["file"] = resource
        resource_def["date_recorded"] = self.get_date_recorded(filepath)
        return resource_def

    def filter_files(self, files, src_ext):
        return [k for k in files if os.path.splitext(k)[1].lower() in [*src_ext]]

    def build_data_dict(self):
        data_dict = OrderedDict()
        data_dict["collections"] = []
        collections_level = os.path.join(self.data_dir)
        for collection in self.collections:
            # first create collection object
            collection_obj = self.get_collection_def(
                name=collection,
            )
            deployments_level = os.path.join(collections_level, collection)
            deployments = [
                k
                for k in os.listdir(deployments_level)
                if os.path.isdir(os.path.join(deployments_level, k))
            ]
            for deployment in deployments:
                deployment_obj = self.get_deployment_def(deployment)
                resources_level = os.path.join(deployments_level, deployment)
                resources = [
                    k
                    for k in os.listdir(resources_level)
                    if os.path.isfile(os.path.join(resources_level, k))
                ]
                resources = self.filter_files(resources, self.all_ext)
                for resource in resources:
                    resource_obj = self.get_resource_def(resource, resources_level)
                    deployment_obj["resources"].append(resource_obj)

                    # add the full path to self.files list
                    self.files.append(os.path.join(resources_level, resource))

                collection_obj["deployments"].append(deployment_obj)

            # TODO: remove; now keep it for the compatibility with the yaml schema
            collection_obj["resources"] = []

            data_dict["collections"].append(collection_obj)

            if len(self.files) == 0:
                raise Exception(
                    (
                        'There is nothing to package. Better check your "Media root" path '
                        "and selected image and video extensions."
                    )
                )
        return data_dict

    def dump_yaml(self, yaml_path):
        with open(yaml_path, "w") as _yaml:
            yaml.dump(self.data_dict, _yaml)


class DataPackageGenerator:
    """
    TODO: docstrings
    """

    def __init__(
        self,
        data_path,
        output_path,
        collections,
        username,
        timezone,
        timezone_ignore_dst=False,
        image_ext=None,
        video_ext=None,
        project=None,
        callback=None,
        package_name_prefix="",
    ):
        self.username = username
        self.project = project
        self.package_name_prefix = package_name_prefix
        self.callback = callback

        if not data_path or not output_path:
            raise Exception('You have to choose both "Media root" and "Output path".')
        if not os.path.isdir(data_path):
            raise Exception(f"There is no directory: {data_path}")
        if not output_path or not os.path.isdir(output_path):
            raise Exception(f"There is no directory: {output_path}")
        self.data_path = data_path
        self.output_path = output_path

        if (image_ext is None or len(image_ext) == 0) and (
            video_ext is None or len(video_ext) == 0
        ):
            raise Exception(
                "You have to provide at least one image or video extension."
            )
        self.image_ext = image_ext
        self.video_ext = video_ext

        # validate collections paths
        for collection in collections:
            collection_path = os.path.join(self.data_path, collection)
            if not os.path.isdir(collection_path):
                raise Exception(f"There is no directory: {collection_path}")
        self.collections = collections

        # validate provided timezone format
        tz_error_msg = (
            "You have to specify a correct timezone. See:\n"
            "https://en.wikipedia.org/wiki/List_of_tz_database_time_zones"
        )
        if not isinstance(timezone, pytz.BaseTzInfo):
            try:
                self.timezone = pytz.timezone(timezone)
            except (pytz.UnknownTimeZoneError, AttributeError):
                raise Exception(tz_error_msg)
        else:
            self.timezone = timezone
        self.timezone_ignore_dst = timezone_ignore_dst

        # build file paths
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        self.log_path = os.path.join(
            self.output_path, self.get_package_name(".log", timestamp)
        )
        self.yaml_path = os.path.join(
            self.output_path, self.get_package_name(".yaml", timestamp)
        )
        self.zip_path = os.path.join(
            self.output_path, self.get_package_name(".zip", timestamp)
        )

        self.yaml_generator = self.get_yaml_generator()
        self.logger = None

    def get_package_name(self, ext, timestamp):
        pname = self.project + "_" + timestamp + "_" + self.username + ext
        if self.package_name_prefix:
            pname = self.package_name_prefix + "_" + pname
        return pname.replace(" ", "_")

    def get_yaml_generator(self):
        return YAMLDefinitionGenerator(
            data_dir=self.data_path,
            collections=self.collections,
            image_ext=self.image_ext,
            video_ext=self.video_ext,
            timezone=self.timezone,
            timezone_ignore_dst=self.timezone_ignore_dst,
            project_name=self.project,
        )

    def make_zip(self, zip_path, files):
        self.logger.info(f"Building the zip archive: {zip_path}")
        with zipfile.ZipFile(zip_path, "w", allowZip64=True) as _zipfile:
            for i, _file in enumerate(files):
                f_archive = os.path.relpath(_file, self.data_path)
                self.logger.info(f"Adding file: {f_archive}")
                if self.callback:
                    self.callback(i, f_archive)
                _zipfile.write(_file, f_archive)

    def run(self):
        # set a data package generator logger
        self.logger = logging.getLogger()
        handler = logging.FileHandler(self.log_path)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter("%(levelname)s:%(message)s"))
        self.logger.addHandler(handler)
        self.logger.info(f"Generating package started at {datetime.datetime.now()}")
        self.logger.info(f"Data path: {self.data_path}")
        self.logger.info(f"Output path: {self.output_path}")
        self.logger.info(f'Collections: {", ".join(self.collections)}')

        try:
            self.yaml_generator.dump_yaml(self.yaml_path)
            self.make_zip(self.zip_path, self.yaml_generator.files)

        except Exception as e:
            for _file in [self.log_path, self.yaml_path, self.zip_path]:
                os.remove(_file)
                raise e
