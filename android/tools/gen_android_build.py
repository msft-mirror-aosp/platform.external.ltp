#!/usr/bin/env python3
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

import argparse
import json
import os
import sys
import shutil
import subprocess
import pwd
import re

# Ensure we can import parser modules from the same directory
tools_dir = os.path.dirname(os.path.realpath(__file__))
sys.path.append(tools_dir)

import make_parser
import make_install_parser

# File paths resolved relative to script's tools_dir
MAKE_DRY_RUN_FILE_NAME = os.path.join(tools_dir, 'dump', 'make_dry_run.dump')
MAKE_INSTALL_DRY_RUN_FILE_NAME = os.path.join(tools_dir, 'dump', 'make_install_dry_run.dump')
DISABLED_TESTS_FILE_NAME = os.path.join(tools_dir, 'disabled_tests.txt')
DISABLED_LIBS_FILE_NAME = os.path.join(tools_dir, 'disabled_libs.txt')
DISABLED_CFLAGS_FILE_NAME = os.path.join(tools_dir, 'disabled_cflags.txt')

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
    def __init__(self, custom_cflags):
        self._bp_result = {}
        self._prebuilt_bp_result = {}
        self._custom_cflags = custom_cflags
        self._unused_custom_cflags = set(custom_cflags)
        self._packages = []

    def UniqueKeepOrder(self, sequence):
        seen = set()
        return [x for x in sequence if not (x in seen or seen.add(x))]

    def ReadCommentedText(self, file_path):
        ret = set()
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                lines = [line.strip() for line in f.readlines()]
                ret = set([s for s in lines if s and not s.startswith('#')])
        return ret

    def ArTargetToLibraryName(self, ar_target):
        return os.path.basename(ar_target)[len('lib'):-len('.a')]

    def BuildExecutable(self, cc_target, local_src_files, local_cflags,
                        local_c_includes, local_libraries, ltp_libs,
                        ltp_libs_used, ltp_names_used):
        base_name = os.path.basename(cc_target)
        if base_name in ltp_names_used:
            print(f'ERROR: base name {base_name} of cc_target {cc_target} already used. Skipping...')
            return
        ltp_names_used.add(base_name)

        if cc_target in self._custom_cflags:
            local_cflags.extend(self._custom_cflags[cc_target])
            self._unused_custom_cflags.remove(cc_target)

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
        module = 'ltp_%s' % install_target.replace('/', '_')
        self._packages.append(module)

        module_dir = os.path.dirname(install_target)
        module_stem = os.path.basename(install_target)

        bp_result = []
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
        self._prebuilt_bp_result[module] = bp_result

    def HandleParsedRule(self, line, rules):
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
        disabled_tests = self.ReadCommentedText(DISABLED_TESTS_FILE_NAME)
        disabled_libs = self.ReadCommentedText(DISABLED_LIBS_FILE_NAME)
        disabled_cflags = self.ReadCommentedText(DISABLED_CFLAGS_FILE_NAME)

        rules = {}
        for line in input_list:
            self.HandleParsedRule(line.strip(), rules)

        ar = rules.get('ar', {})
        cc_link = rules.get('cc_link', {})
        cc_compile = rules.get('cc_compile', {})
        cc_compilelink = rules.get('cc_compilelink', {})
        cc_flags = rules.get('cc_flags', {})
        cc_includes = rules.get('cc_includes', {})
        cc_libraries = rules.get('cc_libraries', {})
        install = rules.get('install', {})

        ltp_libs = set(self.ArTargetToLibraryName(i) for i in ar.keys())
        ltp_libs_used = set()
        ltp_names_used = set()

        for target in cc_flags:
            if '-Wno-error' in cc_flags[target]:
                cc_flags[target].remove('-Wno-error')

        print("Disabled lib tests check...")
        for i in cc_libraries:
            if len(set(cc_libraries[i]).intersection(disabled_libs)) > 0:
                if not os.path.basename(i) in disabled_tests:
                    print(f"Suggested disabled test: {os.path.basename(i)}")

        for target in cc_includes:
            cc_includes[target] = [i for i in cc_includes[target] if os.path.isdir(os.path.join(ltp_root, i))]

        for target in cc_compilelink:
            module_name = os.path.basename(target)
            if module_name in disabled_tests:
                continue
            local_src_files = []
            src_files = cc_compilelink[target]
            for i in src_files:
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
            if not self.ArTargetToLibraryName(target) in ltp_libs_used:
                continue

            local_src_files = set()
            local_cflags = set()
            local_c_includes = set()

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
            if target in disabled_tests or os.path.basename(target) in disabled_tests:
                continue
            local_src_files = install[target]
            assert len(local_src_files) == 1

            if target.startswith("testcases/bin/"):
                self.BuildShellScript(target, local_src_files[0])
            else:
                self.BuildPrebuiltBp(target, local_src_files[0])

    def WriteAndroidBp(self, output_path):
        with open(output_path, 'a') as f:
            for k in sorted(self._bp_result.keys()):
                f.write('\n'.join(self._bp_result[k]))
                f.write('\n')
            self._bp_result = {}

    def WritePrebuiltAndroidBp(self, output_path):
        bp_result = []
        bp_result.append('')
        bp_result.append('package {')
        bp_result.append('    default_applicable_licenses: ["external_ltp_license"],')
        bp_result.append('}')
        for k in sorted(self._prebuilt_bp_result.keys()):
            bp_result.extend(self._prebuilt_bp_result[k])
        self._prebuilt_bp_result = {}
        with open(output_path, 'a') as f:
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
        bp_result = []
        bp_result.append('')
        bp_result.append('package {')
        bp_result.append('    default_applicable_licenses: ["external_ltp_license"],')
        bp_result.append('    default_team: "trendy_team_android_kernel",')
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
        parser = make_parser.MakeParser(ltp_root)
        self.ParseInput(parser.ParseFile(MAKE_DRY_RUN_FILE_NAME), ltp_root)
        parser = make_install_parser.MakeInstallParser(ltp_root)
        self.ParseInput(parser.ParseFile(MAKE_INSTALL_DRY_RUN_FILE_NAME), ltp_root)

    def GetUnusedCustomCFlagsTargets(self):
        return list(self._unused_custom_cflags)

def get_docker_command():
    try:
        res = subprocess.run(['docker', 'ps'], capture_output=True, text=True)
        if res.returncode == 0:
            return ['docker']
    except FileNotFoundError:
        pass

    try:
        res = subprocess.run(['sudo', 'docker', 'ps'], capture_output=True, text=True)
        if res.returncode == 0:
            return ['sudo', 'docker']
    except Exception:
        pass

    return None

def prepare_license_header(license_txt_path, output_path, script_name):
    with open(license_txt_path, 'r') as f:
        lines = f.readlines()
    commented_lines = [line.replace('#', '//') for line in lines]
    
    with open(output_path, 'w') as f:
        f.writelines(commented_lines)
        f.write('\n')
        f.write(f'// This file is autogenerated by {script_name}\n')

def main():
    parser = argparse.ArgumentParser(description="Generate Android.ltp.mk / gen.bp.")
    parser.add_argument('-u', '--update', action='store_true', help="Update option to clean dumps and regenerate.")
    args = parser.parse_args()

    ltp_android_dir = os.path.realpath(os.path.join(tools_dir, '..'))
    ltp_root = os.path.realpath(os.path.join(ltp_android_dir, '..'))
    
    custom_cflags_path = os.path.join(tools_dir, 'custom_cflags.json')
    output_bp = os.path.join(ltp_root, 'gen.bp')
    output_ltp_testcase_bp = os.path.join(ltp_root, 'testcases', 'Android.bp')
    output_ltp_main_bp = os.path.join(ltp_root, 'android', 'Android.bp')
    
    dump_dir = os.path.join(tools_dir, 'dump')

    if args.update:
        print("Update option enabled. Cleaning existing dumps...")
        if os.path.exists(dump_dir):
            shutil.rmtree(dump_dir)

    # 1. Check if make dry run needs to be dumped via Docker
    if not os.path.exists(MAKE_DRY_RUN_FILE_NAME):
        docker_cmd = get_docker_command()
        if not docker_cmd:
            print("Error: docker command not found or requires sudo privileges but failed.")
            sys.exit(1)

        uid = os.getuid()
        gid = os.getgid()
        username = pwd.getpwuid(uid).pw_name
        
        print("LTP make dry_run not dumped. Dumping using Docker container...")
        
        # Build docker image
        build_cmd = docker_cmd + [
            'build',
            '--build-arg', f'userid={uid}',
            '--build-arg', f'groupid={gid}',
            '--build-arg', f'username={username}',
            '--build-arg', f'ltproot={ltp_root}',
            '-t', 'android-gen-ltp',
            tools_dir
        ]
        print(f"Running: {' '.join(build_cmd)}")
        subprocess.run(build_cmd, check=True)

        # Run docker container
        tty_flag = '-it' if sys.stdin.isatty() else '-i'
        run_cmd = docker_cmd + [
            'run',
            tty_flag,
            '--rm',
            '-v', f'{ltp_root}:/src',
            '-w', '/src/android/tools',
            'android-gen-ltp'
        ]
        print(f"Running: {' '.join(run_cmd)}")
        subprocess.run(run_cmd, check=True)

    # 2. Initialize blueprint files with AOSP license header
    license_txt_path = os.path.join(ltp_android_dir, 'AOSP_license_text.txt')
    script_name = os.path.basename(__file__)
    
    print("Writing license headers to blueprint files...")
    prepare_license_header(license_txt_path, output_bp, script_name)
    prepare_license_header(license_txt_path, output_ltp_testcase_bp, script_name)
    prepare_license_header(license_txt_path, output_ltp_main_bp, script_name)

    # 3. Run blueprint generation
    print("Parsing LTP make dry_run output and generating Soong configuration...")
    
    custom_cflags = {}
    if os.path.exists(custom_cflags_path):
        with open(custom_cflags_path) as f:
            custom_cflags = json.load(f)

    generator = BuildGenerator(custom_cflags)
    generator.ParseAll(ltp_root)
    generator.WritePrebuiltAndroidBp(output_ltp_testcase_bp)
    generator.WriteLtpMainAndroidBp(output_ltp_main_bp)
    generator.WriteAndroidBp(output_bp)

    unused_cflags_targs = generator.GetUnusedCustomCFlagsTargets()
    if unused_cflags_targs:
        print(f"NOTE: Tests had custom cflags, but were never seen: {', '.join(unused_cflags_targs)}")

    print("Blueprint generation finished successfully!")

if __name__ == "__main__":
    main()
