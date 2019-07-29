#!/usr/bin/env python

# Copyright 2019 The Kubernetes Authors All rights reserved.
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

import argparse
import os
import subprocess
import sys

COMPONENT_KUBELET = "kubelet"
COMPONENT_CONTAINER_RUNTIME = "container-runtime"
COMPONENT_DOCKER = "docker"

class HealthMonitor(object):
  def __init__(self, component, timeout, cool_down, enable_debug, enable_remedy):
    self._component = component
    self._timeout = timeout
    self._cool_down = cool_down
    self._enable_debug = enable_debug
    self._enable_remedy = enable_remedy

    self._health_check_cmd = []
    self._debug_cmd = []
    self._remedy_cmd = []
    self._prepare()

  def _prepare(self):
    health_check_cmd = ""
    debug_cmd = ""
    remedy_cmd = ""
    if self._component == COMPONENT_KUBELET:
      health_check_cmd = (
        "curl -m %d -f -s -S http://127.0.0.1:10255/healthz") % (
        self._timeout)
      remedy_cmd = "systemctl kill kubelet"
    elif self._component == COMPONENT_CONTAINER_RUNTIME:
      kube_home = "/home/kubernetes"
      container_runtime_name = self._get_container_runtime_name(kube_home)
      if container_runtime_name == COMPONENT_DOCKER:
        # We still need to use `docker ps` when container runtime is "docker".
        # This is because dockershim is still part of kubelet today. When
        # kubelet is down, crictl pods will also fail, and docker will be
        # killed. This is undesirable especially when docker live restore is
        # disabled.
        health_check_cmd = "docker ps"
        # Dump stack of docker daemon for investigation.
        # Log fle name looks like goroutine-stacks-TIMESTAMP and will be saved
        # to the exec root directory, which is /var/run/docker/ on Ubuntu and
        # COS.
        debug_cmd = "pkill -SIGUSR1 dockerd"
      else:
        health_check_cmd = "%s/bin/crictl pods" % kube_home

      health_check_cmd = "timeout %d %s" % (self._timeout, health_check_cmd)
      remedy_cmd = "systemctl kill --kill-who=main %s" % container_runtime_name
      self._component = container_runtime_name
    else:
      print "Health monitoring for component %s is not supported!" % (
        self._component)
      sys.exit(2)

    self._health_check_cmd = health_check_cmd.split()
    self._debug_cmd = debug_cmd.split()
    self._remedy_cmd = remedy_cmd.split()

  def _get_container_runtime_name(self, kube_home):
    kube_env = "%s/kube-env" % kube_home
    if not os.path.exists(kube_env):
      print "The %s file does not exist! Terminate health monitoring" % kube_env
      sys.exit(2)

    container_runtime_name = ""
    f = open(kube_env, 'r')
    for line in f.readlines():
      tokens = line.split("=")
      if "CONTAINER_RUNTIME_NAME" in tokens[0]:
        container_runtime_name = tokens[1]
        break
    f.close()

    if container_runtime_name == "":
      container_runtime_name = COMPONENT_DOCKER
    return container_runtime_name

  def _debug_if_needed(self):
    if not self._enable_debug:
      return
    if len(self._debug_cmd) == 0:
      return
    try:
      subprocess.check_output(self._debug_cmd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError, e:
      print "debug action [%s] for %s failed: %s" % (
        " ".join(self._debug_cmd), self._component, e.output)

  def _remedy_if_needed(self):
    if not self._enable_remedy:
      return
    if len(self._remedy_cmd) == 0:
      return
    try:
      subprocess.check_output(self._remedy_cmd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError, e:
      print "remedy action [%s] for %s failed: %s" % (
        " ".join(self._remedy_cmd), self._component, e.output)

  def _cool_down_if_needed(self):
    if self._cool_down > 0:
      sleep(self._cool_down)

  def check_health(self):
    try:
      subprocess.check_output(self._health_check_cmd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError, e:
      print "%s is unhealthy! %s" % (self._component, e.output)
      self._debug_if_needed()
      self._remedy_if_needed()
      self._cool_down_if_needed()
      sys.exit(1)


if __name__ == '__main__':
  parser = argparse.ArgumentParser(description='Monitor component health')
  parser.add_argument(
    "--component",
    dest="component",
    required=True,
    choices=[COMPONENT_KUBELET, COMPONENT_CONTAINER_RUNTIME],
    help="name of the component to be monitored")
  parser.add_argument(
    "--timeout-seconds",
    dest="timeout",
    required=True,
    type=int,
    help="timeout seconds when running health check command")
  parser.add_argument(
    "--cool-down-seconds",
    dest="cool_down",
    type=int,
    default=0,
    help=("number of seconds to wait before running health check command again "
          "if component is unhealthy"))
  parser.add_argument(
    "--enable-debug",
    dest="enable_debug",
    action="store_true",
    help="perform debug actions when component is unhealthy.")
  parser.add_argument(
    "--enable-remedy",
    dest="enable_remedy",
    action="store_true",
    help="perform remedy actions when component is unhealthy.")
  args = parser.parse_args()

  health_monitor = HealthMonitor(
    args.component,
    args.timeout,
    args.cool_down,
    args.enable_debug,
    args.enable_remedy)
  health_monitor.check_health()
