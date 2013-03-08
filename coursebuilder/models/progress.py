# Copyright 2012 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS-IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Student progress trackers."""

__author__ = 'Sean Lip (sll@google.com)'

import datetime

from tools import verify
from models import StudentPropertyEntity

import transforms


class UnitLessonProgressTracker(object):
    """Progress tracker for a unit/lesson-based linear course."""

    PROPERTY_KEY = 'linear-course-progress'

    # Here are representative examples of the keys for the various entities
    # used in this class:
    #   Unit 1: u.1
    #   Unit 1, Lesson 1: u.1.l.1
    #   Unit 1, Lesson 1, Video 1: u.1.l.1.v.1
    #   Unit 1, Lesson 1, Activity 2: u.1.l.1.a.2
    #   Unit 1, Lesson 1, Activity 2, Block 4: u.1.l.1.a.2.b.4
    #   Assessment 'Pre': s.Pre
    # At the moment, we do not divide assessments into blocks.
    #
    # IMPORTANT NOTE: The values of the keys mean different things depending on
    # whether the entity is a composite entity or not.
    # If it is a composite entity (unit, lesson, activity), then the value is
    #   - 0 if none of its sub-entities has been completed
    #   - 1 if some, but not all, of its sub-entities have been completed
    #   - 2 if all its sub-entities have been completed.
    # If it is not a composite entity (video, block, assessment), then the value
    # is just the number of times the event has been triggered.

    # Constants for recording the state of composite entities.
    # TODO(sll): Change these to enums.
    NOT_STARTED_STATE = 0
    IN_PROGRESS_STATE = 1
    COMPLETED_STATE = 2

    EVENT_CODE_MAPPING = {
        'unit': 'u',
        'lesson': 'l',
        'video': 'v',
        'activity': 'a',
        'block': 'b',
        'assessment': 's',
    }

    def __init__(self, course):
        self._course = course

    def _get_course(self):
        return self._course

    def _get_unit_key(self, unit_id):
        return '%s.%s' % (self.EVENT_CODE_MAPPING['unit'], unit_id)

    def _get_lesson_key(self, unit_id, lesson_id):
        return '%s.%s.%s.%s' % (
            self.EVENT_CODE_MAPPING['unit'], unit_id,
            self.EVENT_CODE_MAPPING['lesson'], lesson_id
        )

    def _get_video_key(self, unit_id, lesson_id, video_id):
        return '%s.%s.%s.%s.%s.%s' % (
            self.EVENT_CODE_MAPPING['unit'], unit_id,
            self.EVENT_CODE_MAPPING['lesson'], lesson_id,
            self.EVENT_CODE_MAPPING['video'], video_id
        )

    def _get_activity_key(self, unit_id, lesson_id, activity_id):
        return '%s.%s.%s.%s.%s.%s' % (
            self.EVENT_CODE_MAPPING['unit'], unit_id,
            self.EVENT_CODE_MAPPING['lesson'], lesson_id,
            self.EVENT_CODE_MAPPING['activity'], activity_id
        )

    def _get_block_key(self, unit_id, lesson_id, activity_id, block_id):
        return '%s.%s.%s.%s.%s.%s.%s.%s' % (
            self.EVENT_CODE_MAPPING['unit'], unit_id,
            self.EVENT_CODE_MAPPING['lesson'], lesson_id,
            self.EVENT_CODE_MAPPING['activity'], activity_id,
            self.EVENT_CODE_MAPPING['block'], block_id
        )

    def _get_assessment_key(self, assessment_id):
        return '%s.%s' % (self.EVENT_CODE_MAPPING['assessment'], assessment_id)

    def _update_unit(self, progress, event_key):
        """Updates a unit's progress if all its lessons have been completed."""
        split_event_key = event_key.split('.')
        assert len(split_event_key) == 2
        unit_id = split_event_key[1]

        if self._get_entity_value(progress, event_key) == self.COMPLETED_STATE:
            return

        # Record that at least one lesson in this unit has been completed.
        self._set_entity_value(progress, event_key, self.IN_PROGRESS_STATE)

        # Check if all lessons in this unit have been completed.
        lessons = self._get_course().get_lessons(unit_id)
        for lesson in lessons:
            # Skip lessons that do not have activities associated with them.
            if not lesson.activity:
                continue
            if not (self._get_lesson_status(
                    progress, unit_id, lesson.id) == self.COMPLETED_STATE):
                return

        # Record that all lessons in this unit have been completed.
        self._set_entity_value(progress, event_key, self.COMPLETED_STATE)

    def _update_lesson(self, progress, event_key):
        """Updates a lesson's progress if its activities have been completed."""
        split_event_key = event_key.split('.')
        assert len(split_event_key) == 4
        unit_id = split_event_key[1]
        lesson_id = split_event_key[3]

        if self._get_entity_value(progress, event_key) == self.COMPLETED_STATE:
            return

        # Record that at least one activity in this lesson has been completed.
        self._set_entity_value(progress, event_key, self.IN_PROGRESS_STATE)

        lessons = self._get_course().get_lessons(unit_id)
        for lesson in lessons:
            if str(lesson.id) == lesson_id and lesson.activity:
                if not (self._get_activity_status(
                        progress, unit_id, lesson_id) == self.COMPLETED_STATE):
                    return

        # Record that all activities in this lesson have been completed.
        self._set_entity_value(progress, event_key, self.COMPLETED_STATE)

    def _update_activity(self, progress, event_key):
        """Updates activity's progress when all interactive blocks are done."""
        split_event_key = event_key.split('.')
        assert len(split_event_key) == 6
        unit_id = split_event_key[1]
        lesson_id = split_event_key[3]

        if self._get_entity_value(progress, event_key) == self.COMPLETED_STATE:
            return

        # Record that at least one block in this activity has been completed.
        self._set_entity_value(progress, event_key, self.IN_PROGRESS_STATE)

        # Get the activity corresponding to this unit/lesson combination.
        activity = verify.Verifier().get_activity_as_python(unit_id, lesson_id)
        for block_id in range(len(activity['activity'])):
            block = activity['activity'][block_id]
            if isinstance(block, dict):
                if not self.is_block_completed(
                        progress, unit_id, lesson_id, block_id):
                    return

        # Record that all blocks in this activity have been completed.
        self._set_entity_value(progress, event_key, self.COMPLETED_STATE)

    UPDATER_MAPPING = {
        'activity': _update_activity,
        'lesson': _update_lesson,
        'unit': _update_unit
    }

    # Dependencies for recording derived events. The key is the current
    # event, and the value is a tuple, each element of which contains:
    # - the dependent entity to be updated
    # - the transformation to apply to the id of the current event to get the
    #       id for the new event
    DERIVED_EVENTS = {
        'block': (
            {
                'entity': 'activity',
                'generate_new_id': (lambda s: '.'.join(s.split('.')[:-2])),
            },
        ),
        'activity': (
            {
                'entity': 'lesson',
                'generate_new_id': (lambda s: '.'.join(s.split('.')[:-2])),
            },
        ),
        'lesson': (
            {
                'entity': 'unit',
                'generate_new_id': (lambda s: '.'.join(s.split('.')[:-2])),
            },
        ),
    }

    def put_video_completed(self, student, unit_id, lesson_id):
        """Records that the given student has completed a video."""
        self._put_event(
            student, 'video', self._get_video_key(unit_id, lesson_id, 0))

    def put_activity_completed(self, student, unit_id, lesson_id):
        """Records that the given student has completed an activity."""
        self._put_event(
            student, 'activity', self._get_activity_key(unit_id, lesson_id, 0))

    def put_block_completed(self, student, unit_id, lesson_id, block_id):
        """Records that the given student has completed an activity block."""
        self._put_event(
            student,
            'block',
            self._get_block_key(unit_id, lesson_id, 0, block_id)
        )

    def put_assessment_completed(self, student, assessment_type):
        """Records that the given student has completed the given assessment."""
        self._put_event(
            student, 'assessment', self._get_assessment_key(assessment_type))

    def put_activity_accessed(self, student, unit_id, lesson_id):
        """Records that the given student has accessed this activity."""
        # This method currently exists because we need to mark activities
        # without interactive blocks as 'completed' when they are accessed.

        # Get the activity corresponding to this unit/lesson combination.
        activity = verify.Verifier().get_activity_as_python(unit_id, lesson_id)
        interactive = False
        for block_id in range(len(activity['activity'])):
            block = activity['activity'][block_id]
            if isinstance(block, dict):
                interactive = True
                break

        if not interactive:
            self.put_activity_completed(student, unit_id, lesson_id)

    def _put_event(self, student, event_entity, event_key):
        """Starts a cascade of updates in response to an event taking place."""
        if event_entity not in self.EVENT_CODE_MAPPING:
            return

        progress = self.get_or_create_progress(student)

        self._update_event(student, progress, event_entity, event_key, True)

        progress.updated_on = datetime.datetime.now()
        progress.put()

    def _update_event(self, student, progress, event_entity, event_key,
                      direct_update=False):
        """Updates statistics for the given event, and for derived events.

        Args:
          student: the student
          progress: the StudentProgressEntity for the student
          event_entity: the name of the affected entity (unit, video, etc.)
          event_key: the key for the recorded event
          direct_update: True if this event is being updated explicitly; False
              if it is being auto-updated.
        """
        if direct_update or event_entity not in self.UPDATER_MAPPING:
            if event_entity in self.UPDATER_MAPPING:
                # This is a derived event, so directly mark it as completed.
                self._set_entity_value(
                    progress, event_key, self.COMPLETED_STATE)
            else:
                # This is not a derived event, so increment its counter by one.
                self._inc(progress, event_key)
        else:
            self.UPDATER_MAPPING[event_entity](self, progress, event_key)

        if event_entity in self.DERIVED_EVENTS:
            for derived_event in self.DERIVED_EVENTS[event_entity]:
                self._update_event(
                    student=student,
                    progress=progress,
                    event_entity=derived_event['entity'],
                    event_key=derived_event['generate_new_id'](event_key),
                )

    def _get_entity_value(self, progress, event_key):
        if not progress.value:
            return None
        return transforms.loads(progress.value).get(event_key)

    def _get_unit_status(self, progress, unit_id):
        return self._get_entity_value(progress, self._get_unit_key(unit_id))

    def _get_lesson_status(self, progress, unit_id, lesson_id):
        return self._get_entity_value(
            progress, self._get_lesson_key(unit_id, lesson_id))

    def is_video_completed(self, progress, unit_id, lesson_id):
        value = self._get_entity_value(
            progress, self._get_video_key(unit_id, lesson_id, 0))
        return value is not None and value > 0

    def _get_activity_status(self, progress, unit_id, lesson_id):
        return self._get_entity_value(
            progress, self._get_activity_key(unit_id, lesson_id, 0))

    def is_block_completed(self, progress, unit_id, lesson_id, block_id):
        value = self._get_entity_value(
            progress, self._get_block_key(unit_id, lesson_id, 0, block_id))
        return value is not None and value > 0

    def is_assessment_completed(self, progress, assessment_type):
        value = self._get_entity_value(
            progress, self._get_assessment_key(assessment_type))
        return value is not None and value > 0

    @classmethod
    def get_or_create_progress(cls, student):
        progress = StudentPropertyEntity.get(student, cls.PROPERTY_KEY)
        if not progress:
            progress = StudentPropertyEntity.create(
                student=student, property_name=cls.PROPERTY_KEY)
            progress.put()
        return progress

    def get_unit_progress(self, student):
        """Returns a dict with the states of each unit."""
        units = self._get_course().get_units()
        progress = self.get_or_create_progress(student)

        result = {}
        for unit in units:
            if unit.type == 'A':
                result[unit.unit_id] = self.is_assessment_completed(
                    progress, unit.unit_id)
            elif unit.type == 'U':
                value = self._get_unit_status(progress, unit.unit_id)
                if value is None:
                    value = 0
                result[unit.unit_id] = value

        return result

    def get_lesson_progress(self, student, unit_id):
        """Returns a dict saying which lessons in this unit are completed."""
        lessons = self._get_course().get_lessons(unit_id)
        progress = self.get_or_create_progress(student)

        result = {}
        for lesson in lessons:
            value = self._get_lesson_status(progress, unit_id, lesson.id)
            if value is None:
                value = 0
            result[lesson.id] = value

        return result

    def _set_entity_value(self, student_property, key, value):
        """Sets the integer value of a student property.

        Note: this method does not commit the change. The calling method should
        call put() on the StudentPropertyEntity.

        Args:
          student_property: the StudentPropertyEntity
          key: the student property whose value should be incremented
          value: the value to increment this property by
        """
        try:
            progress_dict = transforms.loads(student_property.value)
        except (AttributeError, TypeError):
            progress_dict = {}

        progress_dict[key] = value
        student_property.value = transforms.dumps(progress_dict)

    def _inc(self, student_property, key, value=1):
        """Increments the integer value of a student property.

        Note: this method does not commit the change. The calling method should
        call put() on the StudentPropertyEntity.

        Args:
          student_property: the StudentPropertyEntity
          key: the student property whose value should be incremented
          value: the value to increment this property by
        """
        try:
            progress_dict = transforms.loads(student_property.value)
        except (AttributeError, TypeError):
            progress_dict = {}

        if key not in progress_dict:
            progress_dict[key] = 0

        progress_dict[key] += value
        student_property.value = transforms.dumps(progress_dict)
