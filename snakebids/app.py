#!/usr/bin/env python3

"""Tools to generate a Snakemake-based BIDS app."""

import os
import subprocess
import argparse
import logging
import sys
import yaml
import bids
from snakemake import get_argument_parser
from snakemake.io import load_configfile

bids.config.set_option("extension_initial_dot", True)
logger = logging.Logger(__name__)


class ConfigError(Exception):
    """Exception raised for errors with the Snakebids config."""

    def __init__(self, msg):
        self.msg = msg
        Exception.__init__()


class KeyValue(argparse.Action):
    """Class for accepting key=value pairs in argparse"""

    # Constructor calling
    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, dict())

        for value in values:
            # split it into key and value
            key, value = value.split("=")
            # assign into dictionary
            getattr(namespace, self.dest)[key] = value


class SnakemakeHelpAction(argparse.Action):
    """Class for printing snakemake usage in argparse"""

    def __call__(self, parser, namespace, values, option_string=None):
        run("snakemake -h")
        sys.exit(0)


def run(command, env=None):
    """Helper function for running a system command while merging
    stderr/stdout to stdout.

    Parameters
    ----------
    command : list of str
        command to run

    env : dict, optional
        environment variable to set before running the command
    """
    if env is None:
        env = {}

    merged_env = os.environ
    merged_env.update(env)
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=True,
        env=merged_env,
    )
    while True:
        line = process.stdout.readline()
        line = str(line, "utf-8")[:-1]
        print(line)
        if line == "" and process.poll() is not None:
            break
    if process.returncode != 0:
        raise Exception("Non zero return code: %d" % process.returncode)

def get_time_hash():
    """ currently unused """
    import hashlib
    import time

    hash = hashlib.sha1()
    hash.update(str(time.time()).encode('utf-8'))
    return hash.hexdigest()[:8]



SNAKEFILE_CHOICES = [
    "Snakefile",
    "snakefile",
    "workflow/Snakefile",
    "workflow/snakefile",
]


CONFIGFILE_CHOICES = [
            "config/snakebids.yml",
            "config/snakebids.json",
            "snakebids.yml",
            "snakebids.json",
            "config.yml",
            "config.json",
            "config/config.json",
            "config/config.yml"]


class SnakeBidsApp:
    """Snakebids app with config and arguments.

    Parameters
    ----------
    snakemake_dir : str
        Root directory of the snakebids app, containing the config file and
        workflow files.
    skip_parse_args : bool, optional
        If true, the Snakebids app will not attempt to parse input arguments,
        and will only handle the config file.
    out_configfile : str
        Path to the updated configfile (YAML or JSON), relative to the output 
        working directory. This should be the same as the `configfile: ` used
        in your workflow. (default: 'config/snakebids.yml')

    Attributes
    ----------
    config : dict
        Contains all the configuration variables parsed from the config file
        and generated during the initialization of the SnakeBidsApp.
    parser_include_snakemake : ArgumentParser
        Parser including the generic Snakemake parser as a parent. This will
        contain all arguments a Snakemake app can receive.
    parser : ArgumentParser
        Parser including only the arguments specific to this Snakebids app, as
        specified in the config file.
    snakefile : str
        Absolute path to the input Snakefile
            join(snakemake_dir, snakefile_path)
    configfile_path : str
        Relative path to config file (relative to snakemake_dir)
    updated_config : str
        Absolute path to the updated config file to write

    """

    def __init__(self, snakemake_dir, skip_parse_args=False):
        # input argument is the dir where snakemake would be run
        # we use this to locate the config file, and snakefile adding them to
        # generated_config and also add the snakemake_dir to the
        # generated_config, so the workflow can use it to source files from
        # it (e.g. atlases etc..)

        # look for snakebids.yml in the snakemake_dir, quit if not found
        self.configfile_path = None
        for path in CONFIGFILE_CHOICES:
            if os.path.exists(os.path.join(snakemake_dir, path)):
                self.configfile_path = path
                break
        if self.configfile_path is None:
            raise ConfigError(
                "Error: no config file found, tried {}.".format(
                    ", ".join(CONFIGFILE_CHOICES)
                )
            )

        # look for snakefile in the snakemake_dir, quit if not found
        self.snakefile = None
        for snakefile_path in SNAKEFILE_CHOICES:
            if os.path.exists(os.path.join(snakemake_dir, snakefile_path)):
                self.snakefile = os.path.join(snakemake_dir, snakefile_path)
                break
        if self.snakefile is None:
            raise ConfigError(
                "Error: no Snakefile found, tried {}.".format(
                    ", ".join(SNAKEFILE_CHOICES)
                )
            )

        self.config = load_configfile(os.path.join(
                                        snakemake_dir,
                                        self.configfile_path))

        if self.config.get("debug", False):
            logging.basicConfig(level=logging.DEBUG)

        # add path to snakefile to the config -- so workflows can grab files
        # relative to the snakefile folder
        self.config["snakemake_dir"] = snakemake_dir
        self.config["snakefile"] = self.snakefile

        self.parser_include_snakemake = self.__create_parser(
            include_snakemake=True
        )
        self.parser = self.__create_parser()

        if not skip_parse_args:
            self.__parse_args()


    def __create_parser(self, include_snakemake=False):
        """Create a parser with snakemake parser as parent solely for
        displaying help and checking conflicts, but then for actual parsing
        use snakebids parser to parse known args, then pass remaining to
        snakemake.
        """

        if include_snakemake:
            # get snakemake parser
            smk_parser = get_argument_parser()

            # create parser
            parser = argparse.ArgumentParser(
                description="Snakebids helps build BIDS Apps with Snakemake",
                add_help=False,
                parents=[smk_parser],
            )
        else:
            parser = argparse.ArgumentParser(
                description="Snakebids helps build BIDS Apps with Snakemake"
            )

        # add option for printing out snakemake usage
        parser.add_argument(
            "--help_snakemake",
            nargs=0,
            action=SnakemakeHelpAction,
            help=(
                "Options to Snakemake can also be passed directly at the "
                "command-line, use this to print Snakemake usage"
            ),
        )

        # create parser group for app options
        app_group = parser.add_argument_group(
            "SNAKEBIDS", "Options for snakebids app"
        )

        # update the parser with config options
        for name, parse_args in self.config["parse_args"].items():
            app_group.add_argument(name, **parse_args)

        # general parser for
        # --filter_{input_type} {key1}={value1} {key2}={value2}...
        # create filter parsers, one for each input_type
        filter_opts = parser.add_argument_group(
            "BIDS FILTERS",
            "Filters to customize PyBIDS get() as key=value pairs",
        )

        for input_type in self.config["pybids_inputs"].keys():
            argname = f"--filter_{input_type}"
            arglist_default = [
                f"{key}={value}"
                for (key, value) in self.config["pybids_inputs"][input_type][
                    "filters"
                ].items()
            ]
            arglist_default_string = " ".join(arglist_default)

            filter_opts.add_argument(
                argname,
                nargs="+",
                action=KeyValue,
                help=f"(default: {arglist_default_string})",
            )

        # general parser for
        # --wildcards_{input_type} {wildcard1} {wildcard2} ...
        # create wildcards parsers, one for each input_type
        wildcards_opts = parser.add_argument_group(
            "INPUT WILDCARDS",
            "File path entities to use as wildcards in snakemake",
        )

        for input_type in self.config["pybids_inputs"].keys():
            argname = f"--wildcards_{input_type}"
            arglist_default = [
                f"{wc}"
                for wc in self.config["pybids_inputs"][input_type]["wildcards"]
            ]
            arglist_default_string = " ".join(arglist_default)

            wildcards_opts.add_argument(
                argname,
                nargs="+",
                help=f"(default: {arglist_default_string})",
            )

        override_opts = parser.add_argument_group(
            "PATH OVERRIDE",
            (
                "Options for overriding BIDS by specifying absolute paths "
                "that include wildcards, e.g.: "
                "/path/to/my_data/{subject}/t1.nii.gz"
            ),
        )

        # create path override parser
        for input_type in self.config["pybids_inputs"].keys():
            argname = f"--path_{input_type}"
            override_opts.add_argument(argname, default=None)

        return parser

    def __parse_args(self):

        # use snakebids parser to parse the known arguments
        # will pass the rest of args when running snakemake
        all_args = self.parser.parse_known_args()

        args = all_args[0]
        snakemake_args = all_args[1]

        # add snakebids arguments to config
        self.config.update(args.__dict__)

        # add snakemake arguments to config
        self.config.update({"snakemake_args": snakemake_args})

        # argparse adds filter_{input_type} to the config
        # we want to update the pybids_inputs dict with this, then remove the
        # filter_{input_type} dict
        for input_type in self.config["pybids_inputs"].keys():
            arg_filter_dict = self.config[f"filter_{input_type}"]
            if arg_filter_dict is not None:
                self.config["pybids_inputs"][input_type]["filters"].update(
                    arg_filter_dict
                )
            del self.config[f"filter_{input_type}"]

        # add cmdline defined wildcards from the list:
        # wildcards_{input_type}
        for input_type in self.config["pybids_inputs"].keys():
            wildcards_list = self.config[f"wildcards_{input_type}"]
            if wildcards_list is not None:
                self.config["pybids_inputs"][input_type][
                    "wildcards"
                ] += wildcards_list
            del self.config[f"wildcards_{input_type}"]

        # add custom input paths to
        # config['pybids_inputs'][input_type]['custom_path']
        for input_type in self.config["pybids_inputs"].keys():
            custom_path = self.config[f"path_{input_type}"]
            if custom_path is not None:
                self.config["pybids_inputs"][input_type][
                    "custom_path"
                ] = os.path.realpath(custom_path)
            del self.config[f"path_{input_type}"]

        # replace paths with realpaths
        self.config["bids_dir"] = os.path.realpath(self.config["bids_dir"])
        self.config["output_dir"] = os.path.realpath(self.config["output_dir"])


    def write_updated_config(self):
        """Create an updated snakebids config file in the output dir."""
        self.updated_config = os.path.join(
                                    self.config["output_dir"],
                                    self.configfile_path)


        # create the output folder if needed
        os.makedirs(os.path.dirname(self.updated_config), exist_ok=True)

        # write either as JSON or YAML
        config_file_ext = os.path.splitext(self.updated_config)

        time_hash = get_time_hash() # TODO: copy to a time-hashed file too
                                    # for provenance? 
                                    #  unused as of now.. 


        with open(self.updated_config, "w") as f:
            if config_file_ext[-1] == '.json':
                import json
                json.dump(self.config, f, indent=4)
            else: #if not json, then should be yaml or yml
                from collections import OrderedDict
                
                #this is needed to make the output yaml clean
                yaml.add_representer(OrderedDict,
                                        lambda dumper,data: 
                                            dumper.represent_mapping(
                                                'tag:yaml.org,2002:map',
                                                data.items()))
                yaml.dump(dict(self.config),
                            f, 
                            default_flow_style=False,
                            sort_keys=False)

    def run_snakemake(self):
        """Run snake make with that config.

        Workflow snakefile will read snakebids config, create inputs_config,
        and read that in.
        """

        # write updated config
        self.write_updated_config()

        # running the chosen participant level

        analysis_level = self.config["analysis_level"]
        # runs snakemake, using the workflow config and inputs config to
        # override

        # run snakemake command-line (passing any leftover args from argparse)
        snakemake_cmd_list = [
            "snakemake",
            f"--snakefile {self.snakefile}",
            f"--directory {self.config['output_dir']}",
            *self.config["snakemake_args"],
            *self.config["targets_by_analysis_level"][analysis_level],
        ]

        snakemake_cmd = " ".join(snakemake_cmd_list)
        run(snakemake_cmd)
