"""
spore tool module provides base classes for creating new spore tools
SpooreToolCmd: Abstract baseclass for the command that will be triggered
               by the context.
               a. provides access to undo/redo stack
               b. doIt, undoIt, redoIt, finalize should be overwritten to
                  implement functionality
               c. a reference to the brush state object is passed to the command
                  on "toolOnSetup". therefore the "brush_state" attribute can be
                  used to access certain brush properties.
SporeContext: The actual tool context.
              a. Provides basic drawing. Drawing should be overritten by
                 overriting the "canvas" class attribute in the "toolOnSetup"
                 method with another canvas object.
              b. the class attr "state" holds a brush state object which holds
                 various information about the brush as well as all its user
                 settings.
SporeContextCommand: now need to drevie from this class since it does not really
                     provide any functionality other than giving maya acces to
                     to the Context.
"""

import math
import random

from abc import ABCMeta, abstractmethod

import maya.cmds as cmds
import maya.OpenMaya as om
import maya.OpenMayaUI as omui
import maya.OpenMayaMPx as ompx
import maya.OpenMayaRender as omr

from shiboken2 import wrapInstance
from PySide2.QtWidgets import QWidget
from PySide2.QtCore import QObject, QEvent, Signal, Slot, QPoint, Qt
from PySide2.QtGui import QKeyEvent

import canvas
import mesh_utils
import node_utils
import window_utils
import message_utils
import brush_state
import node_state
import event_filter
import brush_utils

reload(canvas)
reload(mesh_utils)
reload(node_utils)
reload(message_utils)
reload(brush_utils)
reload(brush_state)
reload(node_state)
reload(event_filter)


""" -------------------------------------------------------------------- """
""" GLOBALS """
""" -------------------------------------------------------------------- """


K_TOOL_CMD_NAME="sporeToolCmd"
K_CONTEXT_NAME="sporeContext"

K_TRACKING_DICTIONARY = {}


""" -------------------------------------------------------------------- """
""" Sender """
""" -------------------------------------------------------------------- """


class Sender(QObject):
    press = Signal(QPoint)
    drag = Signal(QPoint)
    release = Signal(QPoint)


""" -------------------------------------------------------------------- """
""" TOOL COMMAND """
""" -------------------------------------------------------------------- """


class SporeToolCmd(ompx.MPxToolCommand):
    """ spore base tool command - abstract tool command class ment to be
    subclassed in order to create new spore tool commands """
    k_click, k_drag, k_release = 0, 1, 2

    def __init__(self):
        ompx.MPxToolCommand.__init__(self)
        self.setCommandString(K_TOOL_CMD_NAME)
        K_TRACKING_DICTIONARY[ompx.asHashable(self)] = self

        self.brush_state = None
        self.node_state = None
        self.last_brush_position = None

        self.last_undo_journal = ''

        self.position = om.MVectorArray()
        self.scale = om.MVectorArray()
        self.rotation = om.MVectorArray()
        self.instance_id = om.MIntArray()
        self.normal = om.MVectorArray()
        self.tangent = om.MVectorArray()
        self.u_coord = om.MDoubleArray()
        self.v_coord = om.MDoubleArray()
        self.poly_id = om.MIntArray()
        self.color = om.MVectorArray()
        self.point_id = om.MIntArray()

        self.initial_rotation = om.MVectorArray()
        self.initial_scale = om.MVectorArray()
        self.initial_offset = om.MDoubleArray()
        self.initial_id = om.MIntArray()
        self.spray_coords = []

    def __del__(self):
        print 'DEL COMMAND', K_TRACKING_DICTIONARY, ompx.asHashable(self)
        del K_TRACKING_DICTIONARY[ompx.asHashable(self)]

    @staticmethod
    def creator():
        return ompx.asMPxPtr(SporeToolCmd())

    @staticmethod
    def syntax():
        syntax = om.MSyntax()
        syntax.addArg(om.MSyntax.kDouble)
        syntax.addArg(om.MSyntax.kDouble)
        syntax.addArg(om.MSyntax.kDouble)
        return syntax

    """ -------------------------------------------------------------------- """
    """ reimplemented from MPxToolCommand """
    """ -------------------------------------------------------------------- """

    def doIt(self, args):
        print 'doIt'


    def redoIt(self):
        flag = self.brush_state.action

        if self.node_state.state['mode'] == 'place'\
        or self.node_state.state['mode'] == 'spray': #'place':
            self.place_action(flag)
        #  elif self.node_state.state['mode'] == 1: #'spray':
        #      self.spray_action(flag)
        elif self.node_state.state['mode'] == 'scale': #'scale'
            self.scale_action(flag)
        elif self.node_state.state['mode'] == 'align': #'align'
            self.align_action(flag)
        elif self.node_state.state['mode'] == 'move': #'move':
            self.move_action(flag)
        elif self.node_state.state['mode'] == 'id': #'index':
            self.index_action(flag)

    def undoIt(self):
        print 'undoIt', self.last_undo_journal
        self.last_undo_journal = cmds.undoInfo(q=True, un=True)

    def isUndoable(self):
        return True

    def finalize(self):
        """ Command is finished, construct a string
        for the command for journalling. """

        command = om.MArgList()
        command.addArg(self.commandString())

        if self.node_state.state['mode'] == 'place': #'place':
            command.addArg('place')
            for i in xrange(self.position.length()):
                command.addArg(self.position[i])

        if self.node_state.state['mode'] == 'spray': #'place':
            command.addArg('spray')
            command.addArg(self.position.length())

        # This call adds the command to the undo queue and sets
        # the journal string for the command.
        ompx.MPxToolCommand._doFinalize(self, command)

        for i in xrange(command.length()):
            self.last_undo_journal += ' {}'.format(command.asString(i))

        # reset command variables
        self.position = om.MVectorArray()
        self.scale = om.MVectorArray()
        self.rotation = om.MVectorArray()
        self.instance_id = om.MIntArray()
        self.normal = om.MVectorArray()
        self.tangent = om.MVectorArray()
        self.u_coord = om.MDoubleArray()
        self.v_coord = om.MDoubleArray()
        self.poly_id = om.MIntArray()
        self.color = om.MVectorArray()
        self.point_id = om.MIntArray()

        self.initial_rotation = om.MVectorArray()
        self.initial_scale = om.MVectorArray()
        self.initial_offset = om.MDoubleArray()
        self.initial_id = om.MIntArray()
        self.spray_coords = []

    """ -------------------------------------------------------------------- """
    """ actions """
    """ -------------------------------------------------------------------- """

    def place_action(self, flag):
        position = om.MPoint(self.brush_state.position[0],
                             self.brush_state.position[1],
                             self.brush_state.position[2])
        normal = om.MVector(self.brush_state.normal[0],
                            self.brush_state.normal[1],
                            self.brush_state.normal[2])
        tangent = om.MVector(self.brush_state.tangent[0],
                             self.brush_state.tangent[1],
                             self.brush_state.tangent[2])

        # return if we under min_distance threashold
        if not self.brush_state.drag_mode and self.last_brush_position:
            min_distance = self.node_state.state['min_distance']
            if position.distanceTo(self.last_brush_position) < min_distance:
                return

        self.last_brush_position = position

        #  num_points = self.node_state.length()
        #  if num_points and not self.brush_state.drag_mode:
        #      min_distance = self.node_state.state['min_distance']
        #      last_position = om.MPoint(self.node_state.position[num_points - 1])
        #      if position.distanceTo(last_position) < min_distance:
        #          return

        # set number of samples or default to 1 in place mode
        if self.node_state.state['mode'] == 'spray': # spray mode
            num_samples = self.node_state.state['num_samples']
        else:
            num_samples = 1

        # set last placed points "cache" and begin to sample
        self.set_cache_length(num_samples)
        for i in xrange(num_samples):

            # if in spay mode get random coords on the brush dist or get last values
            if self.node_state.state['mode'] == 'spray': # spray mode
                if self.brush_state.drag_mode and flag != SporeToolCmd.k_click:
                    angle, distance = self.spray_coords[i]
                else:
                    angle = random.uniform(0, 2 * math.pi)
                    distance = random.uniform(0, self.brush_state.radius)
                    self.spray_coords.append((angle, distance))

                # place point on brush disk
                rotation = om.MQuaternion(angle, normal)
                tangential_vector = tangent.rotateBy(rotation)
                rand_pos =  position + tangential_vector * distance
                position, normal = mesh_utils.get_closest_point_and_normal(rand_pos, self.brush_state.target)
                tangent = mesh_utils.get_tangent(normal)

            # get point data
            rotation = self.get_rotation(flag, normal, i)
            scale = self.get_scale(flag, i)
            position = self.get_offset(position, normal, flag, i)
            instance_id = self.get_instance_id(flag, i)
            u_coord, v_coord = mesh_utils.get_uv_at_point(self.brush_state.target, position)
            color = om.MVector(0, 0, 0)

            # set internal cached points
            self.position.set(om.MVector(position), i)
            self.rotation.set(rotation, i)
            self.scale.set(scale, i)
            self.instance_id.set(instance_id, i)
            self.normal.set(normal, i)
            self.tangent.set(tangent, i)
            self.u_coord.set(u_coord, i)
            self.v_coord.set(v_coord, i)
            # TODO - not yet implemented
            self.poly_id.set(0, i)

        # set or append data
        if self.brush_state.drag_mode and flag != SporeToolCmd.k_click:
            self.node_state.set_points(self.point_id,
                                    self.position,
                                    self.scale,
                                    self.rotation,
                                    self.instance_id,
                                    self.normal,
                                    self.tangent,
                                    self.u_coord,
                                    self.v_coord,
                                    self.poly_id,
                                    self.color)

        else:
            self.point_id = self.node_state.append_points(self.position,
                                        self.scale,
                                        self.rotation,
                                        self.instance_id,
                                        self.normal,
                                        self.tangent,
                                        self.u_coord,
                                        self.v_coord,
                                        self.poly_id,
                                        self.color)

        # refresh set plug data and update view
        self.node_state.set_state()

    def align_action(self, flag):
        print 'align'
        position = om.MPoint(self.brush_state.position[0],
                             self.brush_state.position[1],
                             self.brush_state.position[2])
        normal = om.MVector(self.brush_state.normal[0],
                            self.brush_state.normal[1],
                            self.brush_state.normal[2])
        tangent = om.MVector(self.brush_state.tangent[0],
                             self.brush_state.tangent[1],
                             self.brush_state.tangent[2])
        radius = self.brush_state.radius

        neighbour = self.node_state.get_closest_points(position, radius)
        self.set_cache_length(len(neighbour))
        for i, index in enumerate(neighbour):
            rotation = self.node_state.rotation[index]
            print 'init rotation', rotation
            normal = self.node_state.normal[index]
            direction = self.get_alignment(normal)
            rotation = self.rotate_into(direction, rotation)
            print 'new rotation', rotation

            print self.node_state.position[index], i, self.position.length()
            self.position.set(self.node_state.position[index], i)
            self.scale.set(self.node_state.scale[index], i)
            self.rotation.set(rotation, i)
            self.instance_id.set(self.node_state.instance_id[index], i)
            self.normal.set(normal, i)
            self.tangent.set(self.node_state.tangent[index], i)
            self.u_coord.set(self.node_state.u_coord[index], i)
            self.v_coord.set(self.node_state.v_coord[index], i)
            self.poly_id.set(self.node_state.poly_id[index], i)

        self.node_state.set_points(neighbour,
                                self.position,
                                self.scale,
                                self.rotation,
                                self.instance_id,
                                self.normal,
                                self.tangent,
                                self.u_coord,
                                self.v_coord,
                                self.poly_id,
                                self.color)

        self.node_state.set_state()


    def scale_action(self, flag):
        print 'scale'

    def move_action(self, flag):
        print 'move'

    def index_action(self, flag):
        print 'index'

    """ -------------------------------------------------------------------- """
    """ utils """
    """ -------------------------------------------------------------------- """

    def parse_args(self, args):
        pass
        # TODO - generate a new brush state and initialize the tool cmd

    def get_alignment(self, normal):
        """ get the alignment vector """

        #  direction = om.MVector(self.brush_state.normal[0],
        #                         self.brush_state.normal[1],
        #                         self.brush_state.normal[2])
        direction = normal

        if self.node_state.state['align_to'] == 1: # align to world
            print 'align to world'
            direction = om.MVector(0, 1, 0)

        elif self.node_state.state['align_to'] == 2: # align to obj's local
            # TODO - get object up vector
            print 'align to obj'
            pass

        elif self.node_state.state['align_to'] == 3\
        or self.brush_state.align_mode: # align to stroke
            direction = om.MVector(self.brush_state.direction[0],
                                    self.brush_state.direction[1],
                                    self.brush_state.direction[2])

        print 'direction:', direction.x, direction.y, direction.z, self.node_state.state['align_to']
        return direction


    def rotate_into(self, direction, rotation, index=0):
        """ slerp the given rotation values into the direction given
        by the brush_state
        @param direction MVector: the target direction
        @param rotation MVector: current euler rotation """

        #  dir_vector = self.get_alignment(normal)

        mat = om.MTransformationMatrix()

        util = om.MScriptUtil()
        util.createFromDouble(rotation.x, rotation.y, rotation.z)
        rotation_ptr = util.asDoublePtr()
        mat.setRotation(rotation_ptr, om.MTransformationMatrix.kXYZ)

        up_vector = om.MVector(0, 1, 0)
        local_up = up_vector.rotateBy(om.MEulerRotation(math.radians(rotation.x),
                                                        math.radians(rotation.y),
                                                        math.radians(rotation.z)))
        print 'localUp:', local_up.x, local_up.y, local_up.z
        vector_weight = self.node_state.state['strength']
        rotation = om.MQuaternion(direction, local_up, vector_weight)
        #  mat.rotateBy(rotation, om.MSpace.kWorld)
        #  mat.rotateTo(rotation) #, om.MSpace.kWorld)

        mat = mat.asMatrix() * rotation.asMatrix()
        #  rotation = mat.rotation()
        rotation = om.MTransformationMatrix(mat).rotation()

        return om.MVector(math.degrees(rotation.asEulerRotation().x),
                        math.degrees(rotation.asEulerRotation().y),
                        math.degrees(rotation.asEulerRotation().z))

    def set_cache_length(self, length=0):
        """ set the length of the point arrays """
        if length == 0:
            length = self.node_state.state['num_samples']

        print 'set cache length: ', length
        self.position.setLength(length)
        self.scale.setLength(length)
        self.rotation.setLength(length)
        self.instance_id.setLength(length)
        self.normal.setLength(length)
        self.tangent.setLength(length)
        self.u_coord.setLength(length)
        self.v_coord.setLength(length)
        self.poly_id.setLength(length)
        self.color.setLength(length)

        self.initial_scale.setLength(length)
        self.initial_rotation.setLength(length)
        self.initial_offset.setLength(length)
        self.initial_id.setLength(length)

    def get_rotation(self, flag, normal, index=0):
        """ generate new rotation values based on the brush state
        if we are in drag mode we maintain old rotation values and adjust
        rotation to the new normal. we can use the index arg to set a
        specific index for the last placed objects """

        dir_vector = self.get_alignment(normal)
        vector_weight = self.node_state.state['strength']
        world_up = om.MVector(0, 1, 0)
        rotation = om.MQuaternion(world_up, dir_vector, vector_weight)

        # when we in drag mode we want to maintain old rotation values
        if self.brush_state.drag_mode and flag != SporeToolCmd.k_click:
            initial_rotation = self.initial_rotation[index]

        # otherwise we generate new values
        else:
            # get random rotation
            min_rotation = self.node_state.state['min_rot']
            max_rotation = self.node_state.state['max_rot']
            r_x = math.radians(random.uniform(min_rotation[0], max_rotation[0]))
            r_y = math.radians(random.uniform(min_rotation[1], max_rotation[1]))
            r_z = math.radians(random.uniform(min_rotation[2], max_rotation[2]))
            self.initial_rotation.set(om.MVector(r_x, r_y, r_z), index)
            initial_rotation = self.initial_rotation[index]
            #  rotation = brush_utils.get_rotation(self.initial_rotation, direction,

        mat = om.MTransformationMatrix()

        util = om.MScriptUtil()
        util.createFromDouble(initial_rotation.x,
                              initial_rotation.y,
                              initial_rotation.z)
        rotation_ptr = util.asDoublePtr()
        mat.setRotation(rotation_ptr, om.MTransformationMatrix.kXYZ)

        mat = mat.asMatrix() * rotation.asMatrix()
        rotation = om.MTransformationMatrix(mat).rotation()

        return om.MVector(math.degrees(rotation.asEulerRotation().x),
                        math.degrees(rotation.asEulerRotation().y),
                        math.degrees(rotation.asEulerRotation().z))

    def get_scale(self, flag, index=0):
        # when we in drag mode we want to maintain old scale values
        if self.brush_state.drag_mode and flag != SporeToolCmd.k_click:
            scale = self.initial_scale[index]

        # otherweise we generate new values
        else:
            min_scale = self.node_state.state['min_scale']
            max_scale = self.node_state.state['max_scale']
            uniform = self.node_state.state['uni_scale']
            if uniform:
                scale_x = scale_y = scale_z = random.uniform(min_scale[0], max_scale[0])
            else:
                scale_x = random.uniform(min_scale[0], max_scale[0])
                scale_y = random.uniform(min_scale[1], max_scale[1])
                scale_z = random.uniform(min_scale[2], max_scale[2])

            scale = om.MVector(scale_x, scale_y, scale_z)
            self.initial_scale.set(scale, index)

        return scale

    def get_offset(self, position, normal, flag, index=0):

        min_offset = self.node_state.state['min_offset']
        max_offset = self.node_state.state['max_offset']
        if self.brush_state.drag_mode and flag != SporeToolCmd.k_click:
            initial_offset = self.initial_offset[index]
        else:
            initial_offset = random.uniform(min_offset, max_offset)
            self.initial_offset.set(initial_offset, index)

        return position + normal * initial_offset

    def get_instance_id(self, flag, index=0):
        # when we in drag mode we want to maintain old instance id value
        if self.brush_state.drag_mode and flag != SporeToolCmd.k_click:
            instance_id = self.initial_id[index]

        else:
            instance_id = random.randint(self.node_state.state['min_id'],
                                         self.node_state.state['max_id'])
            self.initial_id.set(instance_id, index)
        print 'inst_id', instance_id

        return instance_id

    def initialize_tool_cmd(self, brush_state, node_state):
        """ must be called from the context setup method to
        initialize the tool command with the current brush state.
        commands that need nearest neighbour search should overload this method
        with:
        # self.node_state.build_kd_tree()
        note: building the kd tree might take some time depending on the
        number of points """

        self.brush_state = brush_state
        self.node_state = node_state

        #  node_fn = node_utils.get_dgfn_from_dagpath(self.brush_state.node_name)
        #  data_plug = node_fn.findPlug('instanceData')
        #  self.node_state.initialize_from_plug(data_plug)


""" -------------------------------------------------------------------- """
""" CONTEXT """
""" -------------------------------------------------------------------- """


class SporeContext(ompx.MPxContext):

    def __init__(self):
        ompx.MPxContext.__init__(self)
        self._setTitleString('sporeContext')
        self.setImage("moveTool.xpm", ompx.MPxContext.kImage1)

        self.state = brush_state.BrushState()
        self.node_state = None
        self.msg_io = message_utils.IOHandler()
        self.canvas = None
        self.context_ctrl = None
        self.sender = Sender()
        self.tool_cmd = None

        self.mouse_event_filter = event_filter.MouseEventFilter(self)
        self.key_event_filter = event_filter.KeyEventFilter(self)

        self.connect_signals()

    def connect_signals(self):
        # mouse event signals
        self.mouse_event_filter.clicked.connect(self.clicked)
        self.mouse_event_filter.released.connect(self.released)
        self.mouse_event_filter.dragged.connect(self.dragged)
        self.mouse_event_filter.mouse_moved.connect(self.mouse_moved)
        self.mouse_event_filter.leave.connect(self.leave)

        # key event signals
        self.key_event_filter.ctrl_pressed.connect(self.ctrl_pressed)
        self.key_event_filter.ctrl_released.connect(self.ctrl_released)
        self.key_event_filter.meta_pressed.connect(self.meta_pressed)
        self.key_event_filter.meta_released.connect(self.meta_released)
        self.key_event_filter.shift_pressed.connect(self.shift_pressed)
        self.key_event_filter.shift_released.connect(self.shift_released)
        self.key_event_filter.b_pressed.connect(self.b_pressed)
        self.key_event_filter.b_released.connect(self.b_released)

    def toolOnSetup(self, event):
        """ tool setup:
        - get the node's inMesh and set it as target for the tool
        - update the context controller
        - install mouse & key events
        - build the canvas frot drawing """

        # get spore_node's inMesh and set it as target
        # note: we expect the target node to be selected when we setup the tool
        # if no sporeNode is selected we try to use the last target as fallback
        # if there is no fallback, tool initialization will fail and display a
        # warning
        try: # try to get selection of type sporeNode
            node_name = cmds.ls(sl=True, l=True, type='sporeNode')[0]
        except IndexError:
            node_name = None

        # try to get inMesh of selected spore node
        if node_name:
            self.state.target = node_utils.get_connected_in_mesh(node_name)
            self.state.node = node_name

            if not self.state.target or not self.state.node:
                raise RuntimeError('Failed initializing sporeTool')

        # fallback to old target, just pass since target is already set
        elif self.state.target and self.state.node:
            pass

        # if we neither have a sporeNode selected nor have a fallback, tool init fails
        else:
            self.msg_io.set_message('No sporeNode selected: Can\'t operate on: {}'.format(cmds.ls(sl=1), 1))
            return

        # get node state & cache points for editing
        self.node_state = node_state.SporeState(self.state.node)
        self.node_state.get_node_state()
        if self.node_state.state['mode'] == 'scale'\
        or self.node_state.state['mode'] == 'align'\
        or self.node_state.state['mode'] == 'smooth'\
        or self.node_state.state['mode'] == 'move' \
        or self.node_state.state['mode'] == 'id':
            self.node_state.build_kd_tree()

        # install event filter
        view = window_utils.active_view_wdg()
        view.installEventFilter(self.mouse_event_filter)
        window = window_utils.maya_main_window()
        window.installEventFilter(self.key_event_filter)

        # set up canvas for drawing
        if self.node_state.state['mode'] == 'place': #'place':
            self.canvas = canvas.DotBrush(self.state)
        else:
            self.canvas = canvas.CircularBrush(self.state)



    def toolOffCleanup(self):
        view = window_utils.active_view_wdg()
        view.removeEventFilter(self.mouse_event_filter)
        window = window_utils.maya_main_window()
        window.removeEventFilter(self.key_event_filter)

        self.state.draw = False

        if self.canvas:
            self.canvas.update()
            del self.canvas

        print K_TRACKING_DICTIONARY
        #  self.tool_cmd.finalize()
        #  print 'del hash'
        #  del K_TRACKING_DICTIONARY[ompx.asHashable(self.tool_cmd)]
        #  print 'del cmd'
        #  del self.tool_cmd
        #  self.tool_cmd = None
        #  print K_TRACKING_DICTIONARY
        #  self.tool_cmd.finalize()

    """ -------------------------------------------------------------------- """
    """ mouse events """
    """ -------------------------------------------------------------------- """

    @Slot(QPoint)
    def mouse_moved(self, position):
        """ update the brush as soon as the mouse moves """

        self.state.cursor_x = position.x()
        self.state.cursor_y = position.y()

        result = None
        if not self.state.first_scale:
            result = mesh_utils.hit_test(self.state.target,
                                         self.state.first_x,
                                         self.state.first_y)

        else:
            result = mesh_utils.hit_test(self.state.target,
                                         position.x(),
                                         position.y())

        if result:
            position, normal, tangent = result
            self.state.position = position
            self.state.normal = normal
            self.state.tangent = tangent
            self.state.draw = True

            if not self.state.last_position:
                self.state.last_position = position
            else:
                pos = om.MPoint(position[0], position[1], position[2])
                last_pos = om.MPoint(self.state.last_position[0],
                                     self.state.last_position[1],
                                     self.state.last_position[2])
                stroke_dir = pos - last_pos

                self.state.stroke_direction = (stroke_dir[0],
                                               stroke_dir[1],
                                               stroke_dir[2])

                self.state.last_position = position

        else:
            self.state.draw = False

        #  redraw after coursor has been move
        self.canvas.update()

    @Slot(QPoint)
    def clicked(self, position):
        self.state.action = SporeToolCmd.k_click

        if self.state.draw and not self.state.modify_radius:
            state = self._get_state()
            self.sender.press.emit(state)

            self.node_state.get_node_state()
            #  instanciate the tool command
            tool_cmd = self._newToolCommand()
            print 'toolcmd: ', tool_cmd # spore_tool_cmd.SporeToolCmd.tracking_dir # .get(ompx.asHashable(tool_cmd))
            self.tool_cmd = K_TRACKING_DICTIONARY.get(ompx.asHashable(tool_cmd))
            self.tool_cmd.initialize_tool_cmd(self.state, self.node_state)
            self.tool_cmd.redoIt()


    @Slot(QPoint)
    def dragged(self, position):
        self.state.action = SporeToolCmd.k_drag

        if self.state.draw:
            if self.state.modify_radius:
                if self.state.first_scale:
                    self.state.first_x = position.x()
                    self.state.first_y = position.y()
                    self.state.last_x = position.x()
                    self.state.last_y = position.y()
                    self.state.first_scale = False

                self.modify_radius()
                self.state.last_x = position.x()
                self.state.last_y = position.y()

            else:
                state = self._get_state()
                self.sender.drag.emit(state)
                self.tool_cmd.redoIt()


    @Slot(QPoint)
    def released(self, position):
        self.state.action = SporeToolCmd.k_release

        if self.state.draw and not self.state.modify_radius:
            state = self._get_state()
            self.sender.release.emit(state)

        # finalize tool command
        if self.tool_cmd:
            #  self.tool_cmd.redoIt()
            self.tool_cmd.finalize()
            self.tool_cmd = None

    @Slot()
    def leave(self):
        self.state.draw = False
        self.canvas.update()


    """ -------------------------------------------------------------------- """
    """ key events """
    """ -------------------------------------------------------------------- """

    @Slot()
    def ctrl_pressed(self):
        pass

    @Slot()
    def ctrl_released(self):
        pass

    @Slot()
    def meta_pressed(self):
        pass

    @Slot()
    def meta_released(self):
        pass

    @Slot()
    def shift_pressed(self):
        self.state.drag_mode = True
        self.canvas.update()

    @Slot()
    def shift_released(self):
        self.state.drag_mode = False
        self.canvas.update()


    @Slot()
    def b_pressed(self):
        self.state.modify_radius = True

    @Slot()
    def b_released(self):
        self.state.modify_radius = False
        self.state.first_scale = True

    """ -------------------------------------------------------------------- """
    """ utils """
    """ -------------------------------------------------------------------- """

    def _get_state(self):
        """ get the current state and return it as a dictionary """

        state = {'position': self.state.position,
                 'normal': self.state.normal,
                 'tangent': self.state.tangent,
                 'radius': self.state.radius}

        return state

    def modify_radius(self):
        delta_x = self.state.last_x - self.state.cursor_x

        view = window_utils.active_view()
        cam_dag = om.MDagPath()
        view.getCamera(cam_dag)
        cam_node_fn = node_utils.get_dgfn_from_dagpath(cam_dag.fullPathName())
        cam_coi = cam_node_fn.findPlug('centerOfInterest').asDouble()

        step = delta_x * (cam_coi * -0.025) # TODO - finetune static factor for different scene sizes!
        if (self.state.radius + step) >= 0.01:
            self.state.radius += step

        else:
            self.state.radius = 0.01



""" -------------------------------------------------------------------- """
""" CONTEXT COMMAND """
""" -------------------------------------------------------------------- """


class SporeContextCommand(ompx.MPxContextCommand):
    def __init__(self):
        ompx.MPxContextCommand.__init__(self)

    def makeObj(self):
        return ompx.asMPxPtr(SporeContext())

    @staticmethod
    def creator():
        return ompx.asMPxPtr(SporeContextCommand())

