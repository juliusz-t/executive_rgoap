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

"""
Regressive A* planner with Node, Planner and PlanExecutor
"""


from collections import deque

from rgoap import WorldState


import logging
_logger = logging.getLogger('rgoap')



class Node(object):
    """
    worldstate: states at this node
    action: action that led (regressively) to this node (and that should be run when executing this path forwards)
    possible_prev_nodes: nodes with actions that the planner found possible to help reach this node
                            (empty until planner ran, used for visualization/debugging)
    parent_nodes_path_list: nodes that led (from the goal) to this node
    parent_actions_path_list: actions that led (from the goal) to this node
    note that the parent path lists begin with the goal node and end with this node's parent

    if this node is the goal node:
    - the action is None
    - the path lists are empty
    - also, cost() and heuristic_distance are zero
    """
    def __init__(self, worldstate, action, parent_nodes_path_list, parent_actions_path_list):
        self.worldstate = worldstate
        self.action = action
        self.possible_prev_nodes = []
        self.parent_nodes_path_list = parent_nodes_path_list
        self.parent_actions_path_list = parent_actions_path_list

        self.heuristic_distance = None

    def __str__(self):
        return 'Node %X tCost=%d' % (id(self), self.total_cost())

    def __repr__(self):
#        return '<Node %X cost=%s heur_dist=%s action=%s worldstate=%s>' % \
#            (id(self), self.cost(), self.heuristic_distance, self.action, self.worldstate)
        return '<Node %X cost=%s pathc=%s heur_dist=%s totalc=%s action=%s>' % \
            (id(self), self.cost(), self.path_cost(), self.heuristic_distance, self.total_cost(), self.action)

    def is_goal(self):
        """See class description"""
        return self.action is None

    def parent_node(self):
        return self.parent_nodes_path_list[-1]

    def cost(self):
        """The cost of this node's action"""
        return 0 if self.is_goal() else self.action.cost()

    def path_cost(self):
        """Path cost calculation"""
        return self.cost() + sum(node.cost() for node in self.parent_nodes_path_list)

    def total_cost(self):
        """Path costs plus heuristic distance"""
        return self.path_cost() + self.heuristic_distance

    def _calc_heuristic_distance_for_node(self, start_worldstate):
        # TODO: integrate heuristic calculation nicely
        """Set self.heuristic_distance, a value representing the difference
        between this node's worldstate and the given start worldstate.
        """
        assert self.heuristic_distance is None, "Node heuristic should be calculated only once"

        # check which conditions differ between start and current node
        unsatisfied_conditions_set = self.worldstate.get_unsatisfied_conditions(start_worldstate)

        if self.is_goal():
            # goal node: default distance 1 for each known unsatisfied condition
            self.heuristic_distance = len(unsatisfied_conditions_set)
        else:
            # every other node: sum heuristics for every unsatisified condition
            goal_worldstate = self.parent_nodes_path_list[0].worldstate
            self.heuristic_distance = 0

            for condition in unsatisfied_conditions_set:
                try:
                    goal_value = goal_worldstate.get_condition_value(condition)
                except KeyError:
                    # conditions that weren't part of the goal worldstate but
                    # were involved through actions cannot be compared and get
                    # a default distance
                    self.heuristic_distance += 1
                else:
                    node_value = self.worldstate.get_condition_value(condition)
                    start_value = start_worldstate.get_condition_value(condition)
                    try:
                        distance_total = abs(goal_value - start_value)
                        distance_remaining = abs(node_value - start_value)
                        relative_distance = float(distance_remaining) / distance_total
                        # relative_distance will be 1 at the goal node,
                        # be > 1 if a action moves in the wrong direction or
                        # tend to 0 with the condition being fullfilled gradually
                        assert relative_distance > 0, "If the relative progress" \
                                " results to zero, why is it considered unsatisfied?"
                    except TypeError:
                        # non-numeric conditions get a default distance
                        self.heuristic_distance += 1
                    else:
                        _logger.debug("comparing condition %s: relative_distance = "
                                      "distance_left / distance_total = %s / %s = %s",
                                      condition._state_name, distance_remaining,
                                      distance_total, relative_distance)
                        self.heuristic_distance += relative_distance

            # make sure heuristic distance is less or equal the number of conditions
            self.heuristic_distance = min(len(unsatisfied_conditions_set), self.heuristic_distance)

    # regressive planning
    def get_child_nodes(self, actions, start_worldstate):
        """Returns a list of nodes that are childs of this node and
        contain the given action and start worldstate.
        """
        assert len(self.possible_prev_nodes) == 0, "Node.get_child_nodes is probably not safe to be called twice"
        for action in actions:
            nodes_path_list = self.parent_nodes_path_list[:]
            nodes_path_list.append(self)
            actions_path_list = self.parent_actions_path_list[:]
            actions_path_list.append(action)
            worldstatecopy = WorldState(self.worldstate)
            action.apply_preconditions(worldstatecopy, start_worldstate)
            node = Node(worldstatecopy, action, nodes_path_list, actions_path_list)
            node._calc_heuristic_distance_for_node(start_worldstate)
            self.possible_prev_nodes.append(node)
        return self.possible_prev_nodes



class Planner(object):
    """
    The given start_worldstate must contain every condition ever needed
    by an action or condition.
    """
    # TODO: make ordering of actions possible (e.g. move before lookaround)

    def __init__(self, actions, worldstate, goal):
        self._actions = actions
        self._start_worldstate = worldstate
        self._goal = goal

        self.last_goal_node = None

    def plan(self, start_worldstate=None, goal=None):
        """Plan ...
        Return the node that matches the given start WorldState and
        is the start node for a plan reaching the given Goal.

        If any parameter is not given the data given at initialisation is used.
        """
        # store parameters in instance variables
        if start_worldstate is not None:
            self._start_worldstate = start_worldstate
        if goal is not None:
            self._goal = goal

        # check input
        checked_actions = set()
        for action in self._actions:
            if not action.check_freeform_context():
                _logger.warn("Ignoring action with bad freeform context: %s", action)
            else:
                checked_actions.add(action)

        _logger.info("Planner started\n""actions: %s\n"
                     "start_worldstate: %s\n""goal: %s",
                     self._actions, self._start_worldstate, self._goal)

        # setup goal and loop variables
        goal_worldstate = WorldState()
        self._goal.apply_preconditions(goal_worldstate)
        _logger.debug("goal_worldstate: %s", goal_worldstate)

        goal_node = Node(goal_worldstate, None, [], [])
        goal_node._calc_heuristic_distance_for_node(self._start_worldstate)
        _logger.debug("goal_node: %s", goal_node)
        self.last_goal_node = goal_node

        child_nodes = deque([goal_node])

        loopcount = 0
        while len(child_nodes) != 0:
            loopcount += 1
            if loopcount > 500: # loop limit
                _logger.error("Planner stops because the loop limit (%d) is hit!", loopcount - 1)
                break

            _logger.info("Planning loop #%s", loopcount)
            _logger.debug("nodes (%d): %s", len(child_nodes), child_nodes)

            current_node = child_nodes.popleft()
            _logger.debug("current node (least cost): %s", current_node)
            _logger.debug("current node's worldstate: %s", current_node.worldstate)

            if self._start_worldstate.matches(current_node.worldstate):
                _logger.info("Found plan! Considered nodes: %s; nodes left: %s", loopcount, len(child_nodes))
                _logger.info("plan nodes: %s", current_node.parent_nodes_path_list)
                _logger.info("plan actions: %s", current_node.parent_actions_path_list)
                return current_node

            helpful_actions = self._filter_matching_actions(current_node.worldstate,
                                                            checked_actions)
            new_child_nodes = current_node.get_child_nodes(helpful_actions,
                                                           self._start_worldstate)
            _logger.debug("new child nodes: %s", new_child_nodes)

            # add new nodes and sort. this is stable, so old nodes stay
            # more left in the deque than new nodes with same weight
            child_nodes.extend(new_child_nodes)
            child_nodes = deque(sorted(child_nodes, key=lambda node: node.total_cost()))

        _logger.warn("No plan found.")
        return None

    def _filter_matching_actions(self, node_worldstate, actions):
        """Returns a list of actions that might help between
        start_worldstate and current node_worldstate.
        """
        # check which conditions differ between start and current node
        unsatisfied_conditions_set = node_worldstate.get_unsatisfied_conditions(self._start_worldstate)

        helpful_actions = []
        # check which action might satisfy those conditions
        for action in actions:
            if action.has_satisfying_effects(node_worldstate, self._start_worldstate, unsatisfied_conditions_set):
                _logger.debug("helping action: %s", action)
                helpful_actions.append(action)
            else:
                _logger.debug("helpless action: %s", action)

        return helpful_actions


class PlanExecutor(object):

    def execute(self, start_node, introspector=None):
        """Execute an RGOAP plan, return True on success, False otherwise"""
        assert len(start_node.parent_nodes_path_list) == len(start_node.parent_actions_path_list)

        if start_node.is_goal():
            _logger.info("Executor reached goal node, stopping execution")
            return True

        current_worldstate = start_node.worldstate
        action = start_node.action
        next_node = start_node.parent_node()
        next_worldstate = next_node.worldstate

        if introspector is not None:
            introspector.publish_update(start_node)

        if action.is_valid(current_worldstate):
            if action.check_freeform_context():
                _logger.info("PlanExecutor now executes: %s", action)
                action.run(next_worldstate)
#                _logger.info("Memory is now: %s", action._memory   # only for mem actions)
                return self.execute(next_node, introspector)
            else:
                _logger.error("Action's freeform context isn't valid! Aborting"
                              " executor. action: %s", action)
        else:
            _logger.error("Action isn't valid to worldstate! Aborting"
                          " executor.\n action: %s\n worldstate: %s",
                          action, current_worldstate)

        return False

