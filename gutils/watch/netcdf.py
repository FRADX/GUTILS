#!python
# coding=utf-8
import os
import sys
import shutil
import argparse
import tempfile
from ftplib import FTP
from copy import deepcopy
from datetime import datetime
from collections import namedtuple

import numpy as np
import netCDF4 as nc4
from lxml import etree
from jinja2 import Environment, PackageLoader, select_autoescape
from pyinotify import (
    IN_CLOSE_WRITE,
    IN_MOVED_TO,
    Notifier,
    NotifierError,
    ProcessEvent,
    WatchManager
)

from gutils import setup_cli_logger
from gutils.nc import check_dataset

import logging
L = logging.getLogger(__name__)


class Netcdf2FtpProcessor(ProcessEvent):

    def my_init(self, ftp_url, ftp_user, ftp_pass):
        self.ftp_url = ftp_url
        self.ftp_user = ftp_user
        self.ftp_pass = ftp_pass

    def process_IN_CLOSE(self, event):
        f = namedtuple('Check_Arguments', ['file'])
        args = f(file=event.pathname)
        if self.valid_extension(event.name) and check_dataset(args) == 0:
            self.upload_file(event)

    def process_IN_MOVED_TO(self, event):
        f = namedtuple('Check_Arguments', ['file'])
        args = f(file=event.pathname)
        if self.valid_extension(event.name) and check_dataset(args) == 0:
            self.upload_file(event)

    def valid_extension(self, name):
        _, ext = os.path.splitext(name)
        if ext in ['.nc', 'nc4']:
            return True

        L.error('Unrecognized file extension: {}'.format(ext))
        return False

    def upload_file(self, event):
        ftp = None
        try:
            ftp = FTP(self.ftp_url)
            ftp.login(self.ftp_user, self.ftp_pass)

            with nc4.Dataset(event.pathname) as ncd:
                if not hasattr(ncd, 'id'):
                    raise ValueError("No 'id' global attribute")
                # Change into the correct deployment directory
                try:
                    ftp.cwd(ncd.id)
                except BaseException:
                    ftp.mkd(ncd.id)
                    ftp.cwd(ncd.id)

            with open(event.pathname, 'rb') as fp:
                # Upload NetCDF file
                ftp.storbinary(
                    'STOR {}'.format(event.name),
                    fp
                )
                L.info("Uploaded file: {}".format(event.name))

        except BaseException as e:
            L.error('Could not upload: {} to {}. {}.'.format(event.pathname, self.ftp_url, e))

        finally:
            if ftp is not None:
                ftp.quit()


def create_ftp_arg_parser():

    parser = argparse.ArgumentParser(
        description="Monitor a directory for new netCDF glider data and "
                    "upload the netCDF files to an FTP site."
    )
    parser.add_argument(
        "-d",
        "--data_path",
        help="Path to the glider data netCDF output directory",
        default=os.environ.get('GUTILS_NETCDF_DIRECTORY')
    )
    parser.add_argument(
        "--ftp_url",
        help="Path to the glider data netCDF output directory",
        default=os.environ.get('GUTILS_FTP_URL')
    )
    parser.add_argument(
        "--ftp_user",
        help="FTP username, defaults to 'anonymous'",
        default=os.environ.get('GUTILS_FTP_USER', 'anonymous')
    )
    parser.add_argument(
        "--ftp_pass",
        help="FTP password, defaults to an empty string",
        default=os.environ.get('GUTILS_FTP_PASS', '')
    )
    parser.add_argument(
        "--daemonize",
        help="To daemonize or not to daemonize",
        type=bool,
        default=False
    )

    return parser


def main_to_ftp():
    setup_cli_logger(logging.INFO)

    parser = create_ftp_arg_parser()
    args = parser.parse_args()

    if not args.data_path:
        L.error("Please provide an --data_path agrument or set the "
                "GUTILS_NETCDF_DIRECTORY environmental variable")
        sys.exit(parser.print_usage())

    if not args.ftp_url:
        L.error("Please provide an --ftp_url agrument or set the "
                "GUTILS_FTP_URL environmental variable")
        sys.exit(parser.print_usage())

    wm = WatchManager()
    mask = IN_MOVED_TO | IN_CLOSE_WRITE
    wm.add_watch(
        args.data_path,
        mask,
        rec=True,
        auto_add=True
    )

    processor = Netcdf2FtpProcessor(
        ftp_url=args.ftp_url,
        ftp_user=args.ftp_user,
        ftp_pass=args.ftp_pass,
    )
    notifier = Notifier(wm, processor, read_freq=10)  # Read every 10 seconds
    # Enable coalescing of events. This merges event types of the same type on the same file
    # together over the `read_freq` specified in the Notifier.
    notifier.coalesce_events()

    try:
        L.info("Watching {} and Uploading to {}".format(
            args.data_path,
            args.ftp_url)
        )
        notifier.loop(daemonize=args.daemonize)
    except NotifierError:
        L.exception('Unable to start notifier loop')
        return 1
    except BaseException as e:
        L.exception(e)
        return 1

    L.info("GUTILS netcdf_to_ftp Exited Successfully")
    return 0


def lxml_elements_equal(e1, e2):
    if e1.tag != e2.tag:
        return False
    if e1.text != e2.text:
        return False
    if e1.tail != e2.tail:
        return False
    if e1.attrib != e2.attrib:
        return False
    if len(e1) != len(e2):
        return False

    return all(lxml_elements_equal(c1, c2) for c1, c2 in zip(e1, e2))


datatype_mapping = {
    str: 'String',
    np.dtype('U'): 'String',
    np.dtype('int8'): 'byte',
    np.dtype('int32'): 'int',
    np.dtype('float32'): 'float',
    np.dtype('float64'): 'double',
}


destination_mapping = {
    'profile_lat': 'latitude',
    'profile_lon': 'longitude',
    'profile_time': 'time',
    'time': 'precise_time',
    'lat': 'precise_lat',
    'lon': 'precise_lon',
    'platform': 'meta_platform',
    'crs': 'meta_crs',
}


def netcdf_to_erddap_dataset(datasets_path, netcdf_path, flag_path):
    tmp_handle, tmp_path = tempfile.mkstemp(prefix='gutils_errdap_', suffix='.xml')

    try:
        loader = PackageLoader('gutils', 'templates')
        jenv = Environment(loader=loader, autoescape=select_autoescape(['html', 'xml']))

        # Copy datasets.xml to a tmpfile if it exists
        if os.path.isfile(datasets_path):
            shutil.copy(datasets_path, tmp_path)
        else:
            # Render the base template to the tmpfile
            datasets_template_string = jenv.get_template('erddap_datasets.xml').render()
            with open(tmp_path, 'wt') as f:
                f.write(
                    etree.tostring(
                        etree.fromstring(datasets_template_string),
                        encoding='ISO-8859-1',
                        pretty_print=True,
                        xml_declaration=True
                    ).decode('iso-8859-1')
                )
                f.write('\n')

        deployment_directory = os.path.dirname(netcdf_path)
        deployment_name = os.path.basename(deployment_directory)
        with nc4.Dataset(netcdf_path) as ncd:
            xmlstring = jenv.get_template('erddap_deployment.xml').render(
                deployment_name=deployment_name,
                deployment_directory=deployment_directory,
                deployment_variables=ncd.variables,
                datatype_mapping=datatype_mapping,
                destination_mapping=destination_mapping
            )
        deployment_xml_node = etree.fromstring(xmlstring)

        # Create
        xmltree = etree.parse(tmp_path).getroot()
        find_dataset = etree.XPath("//erddapDatasets/dataset[@datasetID=$name]")

        # Find an existing datasetID within the datasets.xml file
        dnode = find_dataset(xmltree, name=deployment_name)
        if not dnode:
            # No datasetID found, create a new one
            xmltree.append(deployment_xml_node)
            L.debug("Added Deployment: {}".format(deployment_name))
        else:
            if lxml_elements_equal(dnode[0], deployment_xml_node):
                L.debug("Not replacing identical deployment XML node")
                return
            else:
                # Now make sure we don't remove any variables since some could be
                # missing from this file but present in others
                new_vars = [ d.findtext('sourceName') for d in deployment_xml_node.iter('dataVariable') ]
                # iterate over the old_vars and figure out which ones
                # are not in the new_vars
                for dv in dnode[0].iter('dataVariable'):
                    vname = dv.findtext('sourceName')
                    if vname not in new_vars:
                        # Append the old variable block into the new one
                        L.debug('Carried over variable {}'.format(vname))
                        deployment_xml_node.append(deepcopy(dv))

                # Update the existing datasetID with a new XML block
                xmltree.replace(dnode[0], deployment_xml_node)
                L.debug("Replaced Deployment: {}".format(deployment_name))

        # Create tempfile for the new modified file
        new_datasets_handle, new_datasets_path = tempfile.mkstemp(prefix='gutils_erddap_', suffix='.xml')
        with open(new_datasets_path, 'wt') as f:
            f.write(etree.tostring(
                xmltree,
                encoding='ISO-8859-1',
                pretty_print=True,
                xml_declaration=True
            ).decode('iso-8859-1'))
            f.write('\n')

        # Replace old datasets.xml
        os.close(new_datasets_handle)
        os.chmod(new_datasets_path, 0o664)
        shutil.move(new_datasets_path, datasets_path)

    finally:
        # Write dataset update flag if it doesn't exist
        if flag_path is not None:
            flag_tmp_handle, flag_tmp_path = tempfile.mkstemp(prefix='gutils_errdap_', suffix='.flag')
            final_flagfile = os.path.join(flag_path, deployment_name)

            if not os.path.isfile(final_flagfile):
                with open(flag_tmp_path, 'w') as ff:
                    ff.write(datetime.utcnow().isoformat())
                os.chmod(flag_tmp_path, 0o666)
                shutil.move(flag_tmp_path, final_flagfile)

            os.close(flag_tmp_handle)
            if os.path.exists(flag_tmp_path):
                os.remove(flag_tmp_path)

        os.close(tmp_handle)
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


class Netcdf2ErddapProcessor(ProcessEvent):

    def my_init(self, outputs_path, erddap_content_path, erddap_flag_path):
        self.outputs_path = os.path.realpath(outputs_path)
        self.erddap_content_path = os.path.realpath(erddap_content_path)
        self.erddap_flag_path = os.path.realpath(erddap_flag_path)

    def process_IN_CLOSE(self, event):
        if self.valid_extension(event.name):
            self.create_and_update_content(event)

    def process_IN_MOVED_TO(self, event):
        if self.valid_extension(event.name):
            self.create_and_update_content(event)

    def valid_extension(self, name):
        _, ext = os.path.splitext(name)
        if ext in ['.nc', 'nc4']:
            return True
        return False

    def create_and_update_content(self, event):
        datasets_path = os.path.join(self.erddap_content_path, 'datasets.xml')
        netcdf_to_erddap_dataset(
            datasets_path=datasets_path,
            netcdf_path=event.pathname,
            flag_path=self.erddap_flag_path
        )


def create_erddap_arg_parser():

    parser = argparse.ArgumentParser(
        description="Monitor a directory for new netCDF glider deployments and "
                    "edit an ERDDAP datasets.xml file for the deployment."
    )
    parser.add_argument(
        "-d",
        "--data_path",
        help="Path to the glider data netCDF output directory",
        default=os.environ.get('GUTILS_NETCDF_DIRECTORY')
    )
    parser.add_argument(
        "--erddap_content_path",
        help="Path to the ERDDAP content directory",
        default=os.environ.get('GUTILS_ERDDAP_CONTENT_PATH')
    )
    parser.add_argument(
        "--erddap_flag_path",
        help="Path to the ERDDAP flag directory",
        default=os.environ.get('GUTILS_ERDDAP_FLAG_PATH')
    )
    parser.add_argument(
        "--daemonize",
        help="To daemonize or not to daemonize",
        type=bool,
        default=False
    )

    return parser


def main_to_erddap():
    setup_cli_logger(logging.WARNING)

    parser = create_erddap_arg_parser()
    args = parser.parse_args()

    if not args.data_path:
        L.error("Please provide an --data_path agrument or set the "
                "GUTILS_NETCDF_DIRECTORY environmental variable")
        sys.exit(parser.print_usage())

    if not args.erddap_content_path:
        L.error("Please provide an --erddap_content_path agrument or set the "
                "GUTILS_ERDDAP_CONTENT_PATH environmental variable")
        sys.exit(parser.print_usage())

    wm = WatchManager()
    mask = IN_MOVED_TO | IN_CLOSE_WRITE
    wm.add_watch(
        args.data_path,
        mask,
        rec=True,
        auto_add=True
    )

    processor = Netcdf2ErddapProcessor(
        outputs_path=args.data_path,
        erddap_content_path=args.erddap_content_path,
        erddap_flag_path=args.erddap_flag_path
    )
    notifier = Notifier(wm, processor, read_freq=30)  # Read every 30 seconds
    # Enable coalescing of events. This merges event types of the same type on the same file
    # together over the `read_freq` specified in the Notifier.
    notifier.coalesce_events()

    try:
        L.info("Watching {}, updating content at {} and flags at {}".format(
            args.data_path,
            args.erddap_content_path,
            args.erddap_flag_path
        ))
        notifier.loop(daemonize=args.daemonize)
    except NotifierError:
        L.exception('Unable to start notifier loop')
        return 1
    except BaseException as e:
        L.exception(e)
        return 1

    L.info("GUTILS netcdf_to_erddap Exited Successfully")
    return 0
