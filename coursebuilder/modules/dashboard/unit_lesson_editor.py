# Copyright 2013 Google Inc. All Rights Reserved.
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

"""Classes supporting unit and lesson editing."""

__author__ = 'John Orr (jorr@google.com)'

import cgi
import json
import urllib
from controllers.utils import ApplicationHandler
from controllers.utils import BaseRESTHandler
from controllers.utils import XsrfTokenManager
from models import courses
from models import roles
from models import transforms
from modules.oeditor import oeditor
from tools import verify
import filer


# The editor has severe limitations for editing nested lists of objects. First,
# it does not allow one to move a lesson from one unit to another. We need a way
# of doing that. Second, JSON schema specification does not seem to support a
# type-safe array, which has objects of different types. We also want that
# badly :). All in all - using generic schema-based object editor for editing
# nested arrayable polymorphic attributes is a pain...


class CourseOutlineRights(object):
    """Manages view/edit rights for course outline."""

    @classmethod
    def can_view(cls, handler):
        return cls.can_edit(handler)

    @classmethod
    def can_edit(cls, handler):
        return roles.Roles.is_course_admin(handler.app_context)

    @classmethod
    def can_delete(cls, handler):
        return cls.can_edit(handler)

    @classmethod
    def can_add(cls, handler):
        return cls.can_edit(handler)


class UnitLessonEditor(ApplicationHandler):
    """An editor for the unit and lesson titles."""

    def get_edit_unit_lesson(self):
        """Shows editor for the list of unit and lesson titles."""

        key = self.request.get('key')

        exit_url = self.canonicalize_url('/dashboard')
        rest_url = self.canonicalize_url(UnitLessonTitleRESTHandler.URI)
        form_html = oeditor.ObjectEditor.get_html_for(
            self,
            UnitLessonTitleRESTHandler.SCHEMA_JSON,
            UnitLessonTitleRESTHandler.SCHEMA_ANNOTATIONS_DICT,
            key, rest_url, exit_url)

        template_values = {}
        template_values['page_title'] = self.format_title('Edit Course Outline')
        template_values['main_content'] = form_html
        self.render_page(template_values)

    def post_add_unit(self):
        """Adds new unit to a course."""
        self.redirect(self.get_action_url(
            'edit_unit',
            key=courses.Course(self).add_unit().id))

    def post_add_link(self):
        """Adds new link to a course."""
        self.redirect(self.get_action_url(
            'edit_link',
            key=courses.Course(self).add_link().id))

    def post_add_assessment(self):
        """Adds new assessment to a course."""
        self.redirect(self.get_action_url(
            'edit_assessment',
            key=courses.Course(self).add_assessment().id))

    def _render_edit_form_for(self, rest_handler_cls, title):
        """Renders an editor form for a given REST handler class."""
        key = self.request.get('key')

        exit_url = self.canonicalize_url('/dashboard')
        rest_url = self.canonicalize_url(rest_handler_cls.URI)
        delete_url = '%s?%s' % (
            self.canonicalize_url(rest_handler_cls.URI),
            urllib.urlencode({
                'key': key,
                'xsrf_token': cgi.escape(self.create_xsrf_token('delete-unit'))
                }))

        form_html = oeditor.ObjectEditor.get_html_for(
            self,
            rest_handler_cls.SCHEMA_JSON,
            rest_handler_cls.SCHEMA_ANNOTATIONS_DICT,
            key, rest_url, exit_url,
            delete_url=delete_url, delete_method='delete',
            read_only=not filer.is_editable_fs(self.app_context))

        template_values = {}
        template_values['page_title'] = self.format_title(
            'Edit %s' % title)
        template_values['main_content'] = form_html
        self.render_page(template_values)

    def get_edit_unit(self):
        """Shows unit editor."""
        self._render_edit_form_for(UnitRESTHandler, 'Unit')

    def get_edit_link(self):
        """Shows link editor."""
        self._render_edit_form_for(LinkRESTHandler, 'Link')

    def get_edit_assessment(self):
        """Shows assessment editor."""
        self._render_edit_form_for(AssessmentRESTHandler, 'Assessment')


class CommonUnitRESTHandler(BaseRESTHandler):
    """A common super class for all unit REST handlers."""

    def unit_to_dict(self, unused_unit):
        """Converts a unit to a dictionary representation."""
        raise Exception('Not implemented')

    def apply_updates(
        self, unused_unit, unused_updated_unit_dict, unused_errors):
        """Applies changes to a unit; modifies unit input argument."""
        raise Exception('Not implemented')

    def get(self):
        """A GET REST method shared by all unit types."""
        key = self.request.get('key')

        if not CourseOutlineRights.can_view(self):
            transforms.send_json_response(
                self, 401, 'Access denied.', {'key': key})
            return

        unit = courses.Course(self).find_unit_by_id(key)
        if not unit:
            transforms.send_json_response(
                self, 404, 'Object not found.', {'key': key})
            return

        transforms.send_json_response(
            self, 200, 'Success.',
            payload_dict=self.unit_to_dict(unit),
            xsrf_token=XsrfTokenManager.create_xsrf_token('put-unit'))

    def put(self):
        """A PUT REST method shared by all unit types."""
        request = json.loads(self.request.get('request'))
        key = request.get('key')

        if not self.assert_xsrf_token_or_fail(
                request, 'put-unit', {'key': key}):
            return

        if not CourseOutlineRights.can_view(self):
            transforms.send_json_response(
                self, 401, 'Access denied.', {'key': key})
            return

        unit = courses.Course(self).find_unit_by_id(key)
        if not unit:
            transforms.send_json_response(
                self, 404, 'Object not found.', {'key': key})
            return

        payload = request.get('payload')
        updated_unit_dict = transforms.json_to_dict(
            json.loads(payload), self.SCHEMA_DICT)

        errors = []
        self.apply_updates(unit, updated_unit_dict, errors)
        if not errors:
            assert courses.Course(self).put_unit(unit)
            transforms.send_json_response(self, 200, 'Saved.')
        else:
            transforms.send_json_response(self, 412, '\n'.join(errors))

    def delete(self):
        """Handles REST DELETE verb with JSON payload."""
        key = self.request.get('key')

        if not self.assert_xsrf_token_or_fail(
                self.request, 'delete-unit', {'key': key}):
            return

        if not CourseOutlineRights.can_delete(self):
            transforms.send_json_response(
                self, 401, 'Access denied.', {'key': key})
            return

        unit = courses.Course(self).find_unit_by_id(key)
        if not unit:
            transforms.send_json_response(
                self, 404, 'Object not found.', {'key': key})
            return

        assert courses.Course(self).delete_unit(unit)
        transforms.send_json_response(self, 200, 'Deleted.')


class UnitRESTHandler(CommonUnitRESTHandler):
    """Provides REST API to unit."""

    URI = '/rest/course/unit'

    SCHEMA_JSON = """
    {
        "id": "Unit Entity",
        "type": "object",
        "description": "Unit",
        "properties": {
            "key" : {"type": "string"},
            "type": {"type": "string"},
            "title": {"optional": true, "type": "string"},
            "is_draft": {"type": "boolean"}
            }
    }
    """

    SCHEMA_DICT = json.loads(SCHEMA_JSON)

    SCHEMA_ANNOTATIONS_DICT = [
        (['title'], 'Unit'),
        (['properties', 'key', '_inputex'], {
            'label': 'ID', '_type': 'uneditable'}),
        (['properties', 'type', '_inputex'], {
            'label': 'Type', '_type': 'uneditable'}),
        (['properties', 'title', '_inputex'], {'label': 'Title'}),
        oeditor.create_bool_select_annotation(
            ['properties', 'is_draft'], 'Status', 'Draft', 'Published')]

    def unit_to_dict(self, unit):
        assert unit.type == 'U'
        return {
            'key': unit.id,
            'type': verify.UNIT_TYPE_NAMES[unit.type],
            'title': unit.title,
            'is_draft': not unit.now_available}

    def apply_updates(self, unit, updated_unit_dict, unused_errors):
        unit.title = updated_unit_dict.get('title')
        unit.now_available = not updated_unit_dict.get('is_draft')


class LinkRESTHandler(CommonUnitRESTHandler):
    """Provides REST API to link."""

    URI = '/rest/course/link'

    SCHEMA_JSON = """
    {
        "id": "Link Entity",
        "type": "object",
        "description": "Link",
        "properties": {
            "key" : {"type": "string"},
            "type": {"type": "string"},
            "title": {"optional": true, "type": "string"},
            "url": {"optional": true, "type": "string"},
            "is_draft": {"type": "boolean"}
            }
    }
    """

    SCHEMA_DICT = json.loads(SCHEMA_JSON)

    SCHEMA_ANNOTATIONS_DICT = [
        (['title'], 'Link'),
        (['properties', 'key', '_inputex'], {
            'label': 'ID', '_type': 'uneditable'}),
        (['properties', 'type', '_inputex'], {
            'label': 'Type', '_type': 'uneditable'}),
        (['properties', 'title', '_inputex'], {'label': 'Title'}),
        (['properties', 'url', '_inputex'], {'label': 'URL'}),
        oeditor.create_bool_select_annotation(
            ['properties', 'is_draft'], 'Status', 'Draft', 'Published')]

    def unit_to_dict(self, unit):
        assert unit.type == 'O'
        return {
            'key': unit.id,
            'type': verify.UNIT_TYPE_NAMES[unit.type],
            'title': unit.title,
            'url': unit.unit_id,
            'is_draft': not unit.now_available}

    def apply_updates(self, unit, updated_unit_dict, unused_errors):
        unit.title = updated_unit_dict.get('title')
        unit.unit_id = updated_unit_dict.get('url')
        unit.now_available = not updated_unit_dict.get('is_draft')


class AssessmentRESTHandler(CommonUnitRESTHandler):
    """Provides REST API to assessment."""

    URI = '/rest/course/assessment'

    SCHEMA_JSON = """
    {
        "id": "Assessment Entity",
        "type": "object",
        "description": "Assessment",
        "properties": {
            "key" : {"type": "string"},
            "type": {"type": "string"},
            "title": {"optional": true, "type": "string"},
            "is_draft": {"type": "boolean"}
            }
    }
    """

    SCHEMA_DICT = json.loads(SCHEMA_JSON)

    SCHEMA_ANNOTATIONS_DICT = [
        (['title'], 'Assessment'),
        (['properties', 'key', '_inputex'], {
            'label': 'ID', '_type': 'uneditable'}),
        (['properties', 'type', '_inputex'], {
            'label': 'Type', '_type': 'uneditable'}),
        (['properties', 'title', '_inputex'], {'label': 'Title'}),
        oeditor.create_bool_select_annotation(
            ['properties', 'is_draft'], 'Status', 'Draft', 'Published')]

    def unit_to_dict(self, unit):
        assert unit.type == 'A'
        return {
            'key': unit.id,
            'type': verify.UNIT_TYPE_NAMES[unit.type],
            'title': unit.title,
            'is_draft': not unit.now_available}

    def apply_updates(self, unit, updated_unit_dict, unused_errors):
        unit.title = updated_unit_dict.get('title')
        unit.now_available = not updated_unit_dict.get('is_draft')


class UnitLessonTitleRESTHandler(BaseRESTHandler):
    """Provides REST API to unit and lesson titles."""

    URI = '/rest/course/outline'

    SCHEMA_JSON = """
        {
            "type": "object",
            "description": "Course Outline",
            "properties": {
                "outline": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "title": {"type": "string"},
                            "lessons": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "id": {"type": "string"},
                                        "title": {"type": "string"}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        """

    SCHEMA_DICT = json.loads(SCHEMA_JSON)

    SCHEMA_ANNOTATIONS_DICT = [
        (['title'], 'Course Outline'),
        (['properties', 'outline', '_inputex'], {
            'sortable': 'true',
            'label': ''}),
        ([
            'properties', 'outline', 'items',
            'properties', 'title', '_inputex'], {
                '_type': 'uneditable',
                'name': 'name',
                'label': 'Unit'}),
        (['properties', 'outline', 'items', 'properties', 'id', '_inputex'], {
            '_type': 'hidden',
            'name': 'id'}),
        (['properties', 'outline', 'items', 'properties', 'lessons',
          '_inputex'], {
              'sortable': 'true',
              'label': 'Lessons',
              'listAddLabel': 'Add  a new lesson',
              'listRemoveLabel': 'Delete'}),
        (['properties', 'outline', 'items', 'properties', 'lessons', 'items',
          'properties', 'title', '_inputex'], {
              '_type': 'uneditable',
              'name': 'name',
              'label': ''}),
        (['properties', 'outline', 'items', 'properties', 'lessons', 'items',
          'properties', 'id', '_inputex'], {
              '_type': 'hidden',
              'name': 'id'})
        ]

    def get(self):
        """Handles REST GET verb and returns an object as JSON payload."""

        if not CourseOutlineRights.can_view(self):
            transforms.send_json_response(self, 401, 'Access denied.', {})
            return

        course = courses.Course(self)
        outline_data = []
        unit_index = 1
        for unit in course.get_units():
            # TODO(jorr): Need to handle other course objects than just units
            if unit.type == 'U':
                lesson_data = []
                for lesson in course.get_lessons(unit.unit_id):
                    lesson_data.append({
                        'name': lesson.title,
                        'id': lesson.id})
                outline_data.append({
                    'name': '%s - %s' % (unit_index, unit.title),
                    'id': unit.unit_id,
                    'lessons': lesson_data})
                unit_index += 1

        transforms.send_json_response(
            self, 200, 'Success.',
            payload_dict={'outline': outline_data},
            xsrf_token=XsrfTokenManager.create_xsrf_token(
                'unit-lesson-reorder'))

    def put(self):
        """Handles REST PUT verb with JSON payload."""

        if not CourseOutlineRights.can_edit(self):
            transforms.send_json_response(self, 401, 'Access denied.', {})
            return

        # TODO(jorr) Need to actually save the stuff we're sent.
        transforms.send_json_response(self, 405, 'Not yet implemented.', {})
