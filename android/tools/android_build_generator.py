#!/usr/bin/env python
#
# Copyright 2016 - The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

# Parses the output of parse_ltp_{make,make_install} and generates a
# corresponding Android.bp.
#
# This process is split into two steps so this second step can later be replaced
# with an Android.bp generator.

import argparse
import fileinput
import json
import os
import re

import make_parser
import make_install_parser

MAKE_DRY_RUN_FILE_NAME = os.path.join('dump', 'make_dry_run.dump')
MAKE_INSTALL_DRY_RUN_FILE_NAME = os.path.join('dump', 'make_install_dry_run.dump')
DISABLED_TESTS_FILE_NAME = 'disabled_tests.txt'
DISABLED_LIBS_FILE_NAME = 'disabled_libs.txt'
DISABLED_CFLAGS_FILE_NAME = 'disabled_cflags.txt'
TARGET_LIST = [
    {
        "arch": "arm",
        "bitness": "64",
        "extra_test_configs": ["lowmem", "hwasan", "lowmem_hwasan"],
        "targets": ["arm64"],
    },
    {
        "arch": "arm",
        "bitness": "32",
        "extra_test_configs": ["lowmem"],
        "targets": ["arm", "arm64"],
    },
    {
        "arch": "riscv",
        "bitness": "64",
        "targets": ["riscv64"],
    },
    {
        "arch": "x86",
        "bitness": "64",
        "targets": ["x86_64"],
    },
    {
        "arch": "x86",
        "bitness": "32",
        "targets": ["x86", "x86_64"],
    },
]


class BuildGenerator(object):
    '''A class to parse make output and convert the result to Android.bp modules.

    Attributes:
        _bp_result: directory of list of strings for blueprint file keyed by target name
        _prebuilt_bp_result: directory of list of strings for blueprint keyed by target
            name
        _custom_cflags: dict of string (module name) to lists of strings (cflags
            to add for said module)
        _unused_custom_cflags: set of strings; tracks the modules with custom
            cflags that we haven't yet seen
        _packages: list of strings of packages for package list file
    '''

    def __init__(self, custom_cflags):
        self._bp_result = {}
        self._prebuilt_bp_result = {}
        self._custom_cflags = custom_cflags
        self._unused_custom_cflags = set(custom_cflags)
        self._packages = []

    def UniqueKeepOrder(self, sequence):
        '''Get a copy of list where items are unique and order is preserved.

        Args:
          sequence: a sequence, can be a list, tuple, or other iterable

        Returns:
            a list where items copied from input sequence are unique
            and order is preserved.
        '''
        seen = set()
        return [x for x in sequence if not (x in seen or seen.add(x))]

    def ReadCommentedText(self, file_path):
        '''Read pound commented text file into a list of lines.

        Comments or empty lines will be excluded

        Args:
            file_path: string
        '''
        ret = set()
        with open(file_path, 'r') as f:
            lines = [line.strip() for line in f.readlines()]
            ret = set([s for s in lines if s and not s.startswith('#')])

        return ret

    def ArTargetToLibraryName(self, ar_target):
        '''Convert ar target to library name.

        Args:
            ar_target: string
        '''
        return os.path.basename(ar_target)[len('lib'):-len('.a')]

    def BuildExecutable(self, cc_target, local_src_files, local_cflags,
                        local_c_includes, local_libraries, ltp_libs,
                        ltp_libs_used, ltp_names_used):
        '''Build a test module.

        Args:
            cc_target: string
            local_src_files: list of string
            local_cflags: list of string
            local_c_includes: list of string
            local_libraries: list of string
            ltp_libs: list of string
            ltp_libs_used: set of string
            ltp_names_used: set of string, set of already used cc_target basenames
        '''
        base_name = os.path.basename(cc_target)
        if base_name in ltp_names_used:
            print(f'ERROR: base name {base_name} of cc_target {cc_target} already used. Skipping...')
            return
        ltp_names_used.add(base_name)

        if cc_target in self._custom_cflags:
            local_cflags.extend(self._custom_cflags[cc_target])
            self._unused_custom_cflags.remove(cc_target)

        # ltp_defaults already adds the include directory
        local_c_includes = [i for i in local_c_includes if i != 'include']
        target_name = f'ltp_{base_name}'
        target_bp = []

        self._packages.append(target_name)

        target_bp.append('')
        target_bp.append('cc_test {')
        target_bp.append('    name: "%s",' % target_name)
        target_bp.append('    stem: "%s",' % base_name)
        target_bp.append('    defaults: ["ltp_test_defaults"],')

        if len(local_src_files) == 1:
            target_bp.append('    srcs: ["%s"],' % list(local_src_files)[0])
        else:
            target_bp.append('    srcs: [')
            for src in sorted(local_src_files):
                target_bp.append('        "%s",' % src)
            target_bp.append('    ],')

        if len(local_cflags) == 1:
            target_bp.append('    cflags: ["%s"],' % list(local_cflags)[0])
        elif len(local_cflags) > 1:
            target_bp.append('    cflags: [')
            for cflag in sorted(local_cflags):
                target_bp.append('        "%s",' % cflag)
            target_bp.append('    ],')

        if len(local_c_includes) == 1:
            target_bp.append('    local_include_dirs: ["%s"],' % list(local_c_includes)[0])
        elif len(local_c_includes) > 1:
            target_bp.append('    local_include_dirs: [')
            for d in sorted(local_c_includes):
                target_bp.append('        "%s",' % d)
            target_bp.append('    ],')

        bionic_builtin_libs = set(['m', 'rt', 'pthread', 'util'])
        filtered_libs = set(local_libraries).difference(bionic_builtin_libs)

        static_libraries = set(i for i in local_libraries if i in ltp_libs)
        if len(static_libraries) == 1:
            target_bp.append('    static_libs: ["libltp_%s"],' % list(static_libraries)[0])
        elif len(static_libraries) > 1:
            target_bp.append('    static_libs: [')
            for lib in sorted(static_libraries):
                target_bp.append('        "libltp_%s",' % lib)
            target_bp.append('    ],')

        for lib in static_libraries:
            ltp_libs_used.add(lib)

        shared_libraries = set(i for i in filtered_libs if i not in ltp_libs)
        if len(shared_libraries) == 1:
            target_bp.append('    shared_libs: ["lib%s"],' % list(shared_libraries)[0])
        elif len(shared_libraries) > 1:
            target_bp.append('    shared_libs: [')
            for lib in sorted(shared_libraries):
                target_bp.append('        "lib%s",' % lib)
            target_bp.append('    ],')

        target_bp.append('}')
        self._bp_result[target_name] = target_bp

    def BuildStaticLibrary(self, ar_target, local_src_files, local_cflags,
                           local_c_includes):
        '''Build a library module.

        Args:
            ar_target: string
            local_src_files: list of string
            local_cflags: list of string
            local_c_includes: list of string
        '''
        target_name = 'libltp_%s' % self.ArTargetToLibraryName(ar_target)
        target_bp = []
        target_bp.append('')
        target_bp.append('cc_library_static {')
        target_bp.append('    name: "%s",' % target_name)
        target_bp.append('    defaults: ["ltp_defaults"],')

        if len(local_c_includes):
            target_bp.append('    local_include_dirs: [')
            for d in local_c_includes:
                target_bp.append('        "%s",' % d)
            target_bp.append('    ],')

        if len(local_cflags):
            target_bp.append('    cflags: [')
            for cflag in local_cflags:
                target_bp.append('        "%s",' % cflag)
            target_bp.append('    ],')

        target_bp.append('    srcs: [')
        for src in local_src_files:
            target_bp.append('        "%s",' % src)
        target_bp.append('    ],')

        target_bp.append('}')
        self._bp_result[target_name] = target_bp

    def BuildShellScript(self, install_target, local_src_file):
        '''Build a shell script.

        Args:
            install_target: string
            local_src_file: string
        '''
        base_name = os.path.basename(install_target)
        bp_result = []

        module = 'ltp_%s' % install_target.replace('/', '_')
        self._packages.append(module)

        module_dir = os.path.dirname(install_target)
        module_stem = os.path.basename(install_target)

        bp_result.append('')
        bp_result.append('sh_test {')
        bp_result.append('    name: "%s",' % module)
        bp_result.append('    src: "%s",' % local_src_file)
        bp_result.append('    sub_dir: "vts_ltp_tests/%s",' % module_dir)
        bp_result.append('    filename: "%s",' % module_stem)
        bp_result.append('    compile_multilib: "both",')
        bp_result.append('}')

        self._bp_result[module] = bp_result

    def BuildPrebuiltBp(self, install_target, local_src_file):
        '''Build a prebuild module for using Android.bp.

        Args:
            install_target: string
            local_src_file: string
        '''
        base_name = os.path.basename(install_target)
        # The original local_src_file is from external/ltp, but for bp the root
        # will be external/ltp/testcases.
        src = local_src_file.replace('testcases/', '', 1)
        module = 'ltp_%s' % install_target.replace('/', '_')
        module_dir = os.path.dirname(install_target)
        module_stem = os.path.basename(install_target)

        bp_result = []
        bp_result.append('')
        bp_result.append('sh_test {')
        bp_result.append('    name: "%s",' % module)
        bp_result.append('    src: "%s",' % src)
        bp_result.append('    sub_dir: "vts_ltp_tests/%s",' % module_dir)
        bp_result.append('    filename: "%s",' % module_stem)
        bp_result.append('    compile_multilib: "both",')
        bp_result.append('    auto_gen_config: false,')
        bp_result.append('}')

        self._prebuilt_bp_result[base_name] = bp_result
        self._packages.append(module)

    def HandleParsedRule(self, line, rules):
        '''Prepare parse rules.

        Args:
            line: string
            rules: dictionary {string, dictionary}
        '''
        groups = re.match(r'(.*)\[\'(.*)\'\] = \[(.*)\]', line).groups()
        rule = groups[0]
        rule_key = groups[1]
        if groups[2] == '':
            rule_value = []
        else:
            rule_value = list(i.strip()[1:-1] for i in groups[2].split(','))

        rule_value = self.UniqueKeepOrder(rule_value)
        rules.setdefault(rule, {})[rule_key] = rule_value

    def ParseInput(self, input_list, ltp_root):
        '''Parse a interpreted make output and produce Android.bp module.

        Args:
            input_list: list of string
        '''
        disabled_tests = self.ReadCommentedText(DISABLED_TESTS_FILE_NAME)
        disabled_libs = self.ReadCommentedText(DISABLED_LIBS_FILE_NAME)
        disabled_cflags = self.ReadCommentedText(DISABLED_CFLAGS_FILE_NAME)

        rules = {}
        for line in input_list:
            self.HandleParsedRule(line.strip(), rules)

        # .a target -> .o files
        ar = rules.get('ar', {})
        # executable target -> .o files
        cc_link = rules.get('cc_link', {})
        # .o target -> .c file
        cc_compile = rules.get('cc_compile', {})
        # executable target -> .c files
        cc_compilelink = rules.get('cc_compilelink', {})
        # Target name -> CFLAGS passed to gcc
        cc_flags = rules.get('cc_flags', {})
        # Target name -> -I paths passed to gcc
        cc_includes = rules.get('cc_includes', {})
        # Target name -> -l paths passed to gcc
        cc_libraries = rules.get('cc_libraries', {})
        # target -> prebuilt source
        install = rules.get('install', {})

        # All libraries used by any LTP test (built or not)
        ltp_libs = set(self.ArTargetToLibraryName(i) for i in ar.keys())
        # All libraries used by the LTP tests we actually build
        ltp_libs_used = set()
        ltp_names_used = set()

        # Remove -Wno-error from cflags, we don't want to print warnings.
        # Silence individual warnings in ltp_defaults or fix them.
        for target in cc_flags:
            if '-Wno-error' in cc_flags[target]:
                cc_flags[target].remove('-Wno-error')

        print(
            "Disabled lib tests: Test cases listed here are "
            "suggested to be disabled since they require a disabled library. "
            "Please copy and paste them into disabled_tests.txt\n")
        for i in cc_libraries:
            if len(set(cc_libraries[i]).intersection(disabled_libs)) > 0:
                if not os.path.basename(i) in disabled_tests:
                    print(os.path.basename(i))

        print("Disabled_cflag tests: Test cases listed here are "
              "suggested to be disabled since they require a disabled cflag. "
              "Please copy and paste them into disabled_tests.txt\n")
        for i in cc_flags:
            if len(set(cc_flags[i]).intersection(disabled_cflags)) > 0:
                module_name = os.path.basename(i)
                idx = module_name.find('_')
                if idx > 0:
                    module_name = module_name[:idx]
                print(module_name)

        # Remove include directories that don't exist. They're an error in
        # Soong.
        for target in cc_includes:
            cc_includes[target] = [i for i in cc_includes[target] if os.path.isdir(os.path.join(ltp_root, i))]

        for target in cc_compilelink:
            module_name = os.path.basename(target)
            if module_name in disabled_tests:
                continue
            local_src_files = []
            src_files = cc_compilelink[target]
            for i in src_files:
                # some targets may have a mix of .c and .o files in srcs
                # find the .c files to build those .o from cc_compile targets
                if i.endswith('.o'):
                    if i not in cc_compile:
                        raise Exception("Not found: %s when trying to compile target %s" % (i, target))
                    local_src_files.extend(cc_compile[i])
                else:
                    local_src_files.append(i)
            local_cflags = cc_flags[target]
            local_c_includes = cc_includes[target]
            local_libraries = cc_libraries[target]
            if len(set(local_libraries).intersection(disabled_libs)) > 0:
                continue
            if len(set(local_cflags).intersection(disabled_cflags)) > 0:
                continue
            self.BuildExecutable(target, local_src_files, local_cflags,
                                 local_c_includes, local_libraries, ltp_libs,
                                 ltp_libs_used, ltp_names_used)

        for target in cc_link:
            if os.path.basename(target) in disabled_tests:
                continue
            local_src_files = set()
            local_cflags = set()
            local_c_includes = set()
            local_libraries = cc_libraries[target]
            # Accumulate flags for all .c files needed to build the .o files.
            # (Android.bp requires a consistent set of flags across a given target.
            # Thankfully using the superset of all flags in the target works fine
            # with LTP tests.)
            for obj in cc_link[target]:
                for i in cc_compile[obj]:
                    local_src_files.add(i)
                for i in cc_flags[obj]:
                    local_cflags.add(i)
                for i in cc_includes[obj]:
                    local_c_includes.add(i)
            if len(set(local_libraries).intersection(disabled_libs)) > 0:
                continue
            if len(set(local_cflags).intersection(disabled_cflags)) > 0:
                continue

            self.BuildExecutable(target, local_src_files, local_cflags,
                                 local_c_includes, local_libraries, ltp_libs,
                                 ltp_libs_used, ltp_names_used)

        for target in ar:
            # Disabled ltp library is already excluded
            # since it won't be in ltp_libs_used
            if not self.ArTargetToLibraryName(target) in ltp_libs_used:
                continue

            local_src_files = set()
            local_cflags = set()
            local_c_includes = set()

            # TODO: disabled cflags

            for obj in ar[target]:
                for i in cc_compile[obj]:
                    local_src_files.add(i)
                for i in cc_flags[obj]:
                    local_cflags.add(i)
                for i in cc_includes[obj]:
                    local_c_includes.add(i)

            if len(set(local_cflags).intersection(disabled_cflags)) > 0:
                continue

            local_src_files = sorted(local_src_files)
            local_cflags = sorted(local_cflags)
            local_c_includes = sorted(local_c_includes)

            self.BuildStaticLibrary(target, local_src_files, local_cflags,
                                    local_c_includes)

        for target in install:
            # Check if the absolute path to the prebuilt (relative to LTP_ROOT)
            # is disabled. This is helpful in case there are duplicates with basename
            # of the prebuilt.
            #  e.g.
            #   ./ testcases / kernel / fs / fs_bind / move / test01
            #   ./ testcases / kernel / fs / fs_bind / cloneNS / test01
            #   ./ testcases / kernel / fs / fs_bind / regression / test01
            #   ./ testcases / kernel / fs / fs_bind / rbind / test01
            #   ./ testcases / kernel / fs / fs_bind / bind / test01
            if target in disabled_tests:
                continue
            if os.path.basename(target) in disabled_tests:
                continue
            local_src_files = install[target]
            assert len(local_src_files) == 1

            if target.startswith("testcases/bin/"):
                self.BuildShellScript(target, local_src_files[0])
            else:
                self.BuildPrebuiltBp(target, local_src_files[0])

    def WriteAndroidBp(self, output_path):
        '''Write parse result to blueprint file.

        Args:
            output_path: string
        '''
        with open(output_path, 'a') as f:
            for k in sorted(self._bp_result.keys()):
                f.write('\n'.join(self._bp_result[k]))
                f.write('\n')
            self._bp_result = {}

    def WritePrebuiltAndroidBp(self, output_path):
        '''Write parse result to blueprint file.

        Args:
            output_path: string
        '''
        bp_result = []
        bp_result.append('')
        bp_result.append('package {')
        bp_result.append('    default_applicable_licenses: ["external_ltp_license"],')
        bp_result.append('}')
        for k in sorted(self._prebuilt_bp_result.keys()):
            bp_result.extend(self._prebuilt_bp_result[k])
        self._prebuilt_bp_result = {}
        with open(output_path, 'a') as f:
            for k in sorted(self._prebuilt_bp_result.keys()):
                f.write('\n'.join(self._prebuilt_bp_result[k]))
                f.write('\n')
            self._prebuilt_bp_result = {}
            f.write('\n'.join(bp_result))
            f.write('\n')

    def ArchString(self, arch, bitness, lowmem=False, hwasan=False):
        if bitness == '32':
            arch_string = arch
        else:
            arch_string = f'{arch}_{bitness}'
        if lowmem:
            arch_string += '_lowmem'
        if hwasan:
            arch_string += '_hwasan'
        return arch_string

    def BuildConfigGenrule(self, arch, bitness, targets, extra_test_configs=None):
        extra_test_configs = extra_test_configs if extra_test_configs else []
        bp_result = []
        arch_string = self.ArchString(arch, bitness)

        bp_result.append('')
        bp_result.append('genrule {')
        bp_result.append('    name: "ltp_config_%s",' % arch_string)
        bp_result.append('    out: ["vts_ltp_test_%s.xml"],' % arch_string)
        bp_result.append('    tools: ["gen_ltp_config"],')
        bp_result.append('    cmd: "$(location gen_ltp_config) --arch %s --bitness %s $(out)",' % (arch, bitness))
        bp_result.append('}')

        for config in extra_test_configs:
            lowmem = 'lowmem' in config
            hwasan = 'hwasan' in config
            arch_string = self.ArchString(arch, bitness, lowmem, hwasan)

            bp_result.append('')
            bp_result.append('genrule {')
            bp_result.append('    name: "ltp_config_%s",' % arch_string)
            bp_result.append('    out: ["vts_ltp_test_%s.xml"],' % arch_string)
            bp_result.append('    tools: ["gen_ltp_config"],')
            bp_result.append('    cmd: "$(location gen_ltp_config) --arch %s --bitness %s --low-mem %r --hwasan %r $(out)",' % (arch, bitness, lowmem, hwasan))
            bp_result.append('}')
        return bp_result

    def BuildPackageList(self):
        bp_result = []
        bp_result.append('')
        bp_result.append('LTP_TESTS = [')
        bp_result.append('    ":ltp_runtests",')
        for package in sorted(self._packages):
            bp_result.append('    ":%s",' % package)
        bp_result.append(']')
        return bp_result

    def BuildLTPTestSuite(self, arch, bitness, targets, extra_test_configs=None):
        extra_test_configs = extra_test_configs if extra_test_configs else []
        bp_result = []
        arch_string = self.ArchString(arch, bitness)

        bp_result.append('')
        bp_result.append('sh_test {')
        bp_result.append('    name: "vts_ltp_test_%s",' % arch_string)
        bp_result.append('    src: "empty.sh",')
        bp_result.append('    test_config: ":ltp_config_%s",' % arch_string)
        bp_result.append('    test_suites: [')
        bp_result.append('        "general-tests",')
        bp_result.append('        "vts",')
        bp_result.append('    ],')
        bp_result.append('    enabled: false,')

        if bitness == '32':
            bp_result.append('    compile_multilib: "32",')

        bp_result.append('    arch: {')
        for target in targets:
            bp_result.append('        %s: {' % target)
            bp_result.append('            enabled: true,')
            bp_result.append('        },')
        bp_result.append('    },')

        if extra_test_configs:
            bp_result.append('    extra_test_configs: [')
            for config in extra_test_configs:
                lowmem = 'lowmem' in config
                hwasan = 'hwasan' in config
                arch_string = self.ArchString(arch, bitness, lowmem, hwasan)
                bp_result.append('        ":ltp_config_%s",' % arch_string)
            bp_result.append('    ],')

        bp_result.append('    data: LTP_TESTS,')
        bp_result.append('}')
        return bp_result

    def WriteLtpMainAndroidBp(self, output_path):
        '''Write the blueprint file of ltp main module.

        Args:
            output_path: string
        '''
        bp_result = []
        bp_result.append('')
        bp_result.append('package {')
        bp_result.append('    default_applicable_licenses: ["external_ltp_license"],')
        bp_result.append('}')

        bp_result.extend(self.BuildPackageList())

        for target in TARGET_LIST:
            bp_result.extend(self.BuildConfigGenrule(**target))

        for target in TARGET_LIST:
            bp_result.extend(self.BuildLTPTestSuite(**target))

        with open(output_path, 'a') as f:
            f.write('\n'.join(bp_result))
            f.write('\n')

    def ParseAll(self, ltp_root):
        '''Parse outputs from both 'make' and 'make install'.

        Args:
            ltp_root: string
        '''
        parser = make_parser.MakeParser(ltp_root)
        self.ParseInput(parser.ParseFile(MAKE_DRY_RUN_FILE_NAME), ltp_root)
        parser = make_install_parser.MakeInstallParser(ltp_root)
        self.ParseInput(parser.ParseFile(MAKE_INSTALL_DRY_RUN_FILE_NAME), ltp_root)

    def GetUnusedCustomCFlagsTargets(self):
        '''Get targets that have custom cflags, but that weren't built.'''
        return list(self._unused_custom_cflags)


def main():
    parser = argparse.ArgumentParser(
        description='Generate Android.bp from parsed LTP make output')
    parser.add_argument(
        '--ltp_root', dest='ltp_root', required=True, help='LTP root dir')
    parser.add_argument(
        '--output_prebuilt_ltp_testcase_bp_path',
        dest='output_prebuilt_ltp_testcase_bp_path',
        required=True,
        help='output prebuilt test case blueprint path')
    parser.add_argument(
        '--output_ltp_main_bp_path',
        dest='output_ltp_main_bp_path',
        required=True,
        help='output ltp main blueprint path')
    parser.add_argument(
        '--output_bp_path',
        dest='output_bp_path',
        required=True,
        help='output blueprint path')
    parser.add_argument(
        '--custom_cflags_file',
        dest='custom_cflags_file',
        required=True,
        help='file with custom per-module cflags. empty means no file.')
    args = parser.parse_args()

    custom_cflags = {}
    if args.custom_cflags_file:
        # The file is expected to just be a JSON map of string -> [string], e.g.
        # {"testcases/kernel/syscalls/getcwd/getcwd02": ["-DFOO", "-O3"]}
        with open(args.custom_cflags_file) as f:
            custom_cflags = json.load(f)

    generator = BuildGenerator(custom_cflags)
    generator.ParseAll(args.ltp_root)
    generator.WritePrebuiltAndroidBp(args.output_prebuilt_ltp_testcase_bp_path)
    generator.WriteLtpMainAndroidBp(args.output_ltp_main_bp_path)
    generator.WriteAndroidBp(args.output_bp_path)

    unused_cflags_targs = generator.GetUnusedCustomCFlagsTargets()
    if unused_cflags_targs:
        print('NOTE: Tests had custom cflags, but were never seen: {}'.format(
            ', '.join(unused_cflags_targs)))

    print('Finished!')


if __name__ == '__main__':
    main()
