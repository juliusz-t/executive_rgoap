#!/usr/bin/env python

# Copyright (c) 2013, Felix Kolbe
# All rights reserved. BSD License
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# * Redistributions of source code must retain the above copyright
#   notice, this list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright
#   notice, this list of conditions and the following disclaimer in the
#   documentation and/or other materials provided with the distribution.
#
# * Neither the name of the {organization} nor the names of its
#   contributors may be used to endorse or promote products derived
#   from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.


import roslib; roslib.load_manifest('rgoap')

from time import sleep

import rgoap

from common import Condition, WorldState, stringify, stringify_dict
from memory import Memory
from planning import Planner, PlanExecutor


import logging
_logger = logging.getLogger('rgoap')



class Runner(object):
    """
    self.memory: memory to be used for conditions and actions
    self.worldstate: the default/start worldstate
    self.actions: the actions this runner uses
    self.planner: the planner this runner uses
    """

    def __init__(self, config_module=None):
        """
        param:config_module: a scenario/robot specific module to prepare setup,
                that has the following members:
                    get_all_conditions() -> return a list of conditions
                    get_all_actions() -> return a list of actions
        """
        self.memory = Memory()
        self.worldstate = WorldState()
        self.actions = set()

        if config_module is not None:
            for condition in config_module.get_all_conditions(self.memory):
                Condition.add(condition)
            for action in config_module.get_all_actions(self.memory):
                self.actions.add(action)

        self.planner = Planner(self.actions, self.worldstate, None)

        self._last_goal = None
        self._preempt_requested = False # preemption mechanism


    def __repr__(self):
        return '<%s memory=%s worldstate=%s actions=%s planner=%s>' % (self.__class__.__name__,
                                self.memory, self.worldstate, self.actions, self.planner)


    def request_preempt(self):
        self._preempt_requested = True

    def preempt_requested(self):
        return self._preempt_requested

    def service_preempt(self):
        self._preempt_requested = False


    def _update_worldstate(self):
        """update worldstate to reality"""
        Condition.initialize_worldstate(self.worldstate)
        _logger.info("worldstate initialized/updated to: %s", self.worldstate)

    def _check_conditions(self):
        # check for any still uninitialised condition
        for (condition, value) in self.worldstate._condition_values.iteritems():
            if value is None:
                _logger.warn("Condition still 'None': %s", condition)


    def update_and_plan(self, goal, tries=1, introspection=False):
        """update worldstate and call self.plan(...), repeating for
        number of tries or until a plan is found"""
        assert tries >= 1
        while tries > 0:
            tries -= 1
            self._update_worldstate()
            start_node = self.plan(goal, introspection)
            if start_node is not None:
                break
            if tries > 0: # if there are tries left
                _logger.warn("Runner retrying in update_and_plan")
        return start_node


    def plan(self, goal, introspection=False):
        """plan for given goal and return start_node of plan or None"""
        self._check_conditions()
        return self.planner.plan(goal=goal)



    def plan_and_execute_goals(self, goals):
        """Sort goals by usability and try to plan and execute one by one until
        one goal is achieved"""
        self._update_worldstate()

        # sort goals
        goals.sort(key=lambda goal: goal.usability, reverse=True)

        if _logger.isEnabledFor(logging.INFO):
            _logger.info("Available goals:\n%s", stringify(goals, '\n'))

        # plan until plan for one goal found
        for goal in goals:
            # skip goal we used last time
            if self._last_goal is goal:
                continue

            if self.preempt_requested():
                self.service_preempt()
                return 'preempted'

            plan = self.plan(goal)
            if plan is None:
                continue # try next goal

            # execution
            self._last_goal = goal
            _logger.info("Executing most usable goal: %s", goal)
            _logger.info("With plan: %s", plan)
            outcome = self.execute(plan, introspection=True)
            _logger.info("Most usable goal returned: %s", outcome)
            if outcome == 'aborted':
                _logger.warn("Executed goal return 'aborted', trying next goal")
                continue # try next goal

            return outcome

        _logger.error("For no goal a plan could be found!")
        outcome = 'aborted'

        return outcome


    def update_and_plan_and_execute(self, goal, tries=1, introspection=False):
        """loop that updates, plans and executes until the goal is reached"""
        outcome = None
        # replan and retry on failure as long as a plan is found
        while not rgoap.is_shutdown():
            if self.preempt_requested():
                self.service_preempt()
                return 'preempted'

            start_node = self.update_and_plan(goal, tries, introspection)

            if start_node is None:
                # TODO: maybe at this point update and replan, regardless of 'tries'? reality might have changed
                _logger.error("RGOAP Runner aborts, no plan found!")
                return 'aborted'

            outcome = self.execute(start_node, introspection)

            if outcome != 'aborted':
                break # retry

            # check failure
            _logger.warn("RGOAP Runner execution fails, replanning..")

            self._update_worldstate()
            if not goal.is_valid(self.worldstate):
                _logger.warn("Goal isn't valid in current worldstate")
            else:
                _logger.error("Though goal is valid in current worldstate, the plan execution failed!?")

        # until we are succeeding or are preempted
        return outcome


    def execute(self, start_node, introspection=False):
        success = PlanExecutor().execute(start_node)
        return success

    def print_worldstate_loop(self):
        while not rgoap.is_shutdown():
            self._update_worldstate()
            _logger.info("%s", self.worldstate)
            sleep(2)

