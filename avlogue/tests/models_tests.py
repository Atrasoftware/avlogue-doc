"""
Avlogue models test cases.
"""
import os

import mock
from django.core.files.base import File
from django.core.files.storage import FileSystemStorage
from django.test import TestCase

from avlogue.encoders import default_encoder
from avlogue.models import VideoFile, VideoFormat, AudioFormat, AudioFile, VideoFormatSet, AudioFormatSet
from avlogue.tests import factories
from avlogue.tests import mocks


class ModelsTestCase(TestCase):
    """
    Avlogue model tests.
    """

    fixtures = ['media-formats.json']

    def test_audio_video_formats(self):
        for media_format in (VideoFormat.objects.first(), AudioFormat.objects.first()):
            self.assertEqual(str(media_format), media_format.name)

        for media_format_set in (VideoFormatSet.objects.first(), AudioFormatSet.objects.first()):
            self.assertEqual(str(media_format_set), media_format_set.name)

    def test_audio_video_file_crud(self):
        """
        Tests CRUD for AudioFile/VideoFile.
        """

        def assert_media_file_fields(media_file):
            """
            Assert that AudioFile/VideoFile object has the same fields as encoder provides.
            :param media_file:
            :return:
            """
            file_info = default_encoder.get_file_info(media_file.file.path)
            for key, val in file_info.items():
                self.assertEqual(getattr(media_file, key), val)

        def test_crud(media_format_cls, media_file_cls, file_factory):
            media_format = media_format_cls.objects.first()
            with file_factory(file_name='test_{}_file'.format(media_format.name),
                              encode_format=media_format) as file_path:
                # Test create by file path
                media_file = media_file_cls.objects.create_from_file(file_path)
                self.assertIsNotNone(media_file)
                self.assertTrue(str(media_file), 'test_media_file.{}'.format(media_format.container))
                media_file.delete()

                # Test create by file object
                media_file = media_file_cls.objects.create_from_file(File(open(file_path, mode='rb')))
                self.assertIsNotNone(media_file)
                assert_media_file_fields(media_file)

                # Check deletion of an old file during AudioFile/VideoFile file changing
                with file_factory(file_name='new_test_media_file', encode_format=media_format) as new_file_path:
                    media_old_file_path = media_file.file.path
                    self.assertTrue(os.path.exists(media_old_file_path))

                    media_file.file = File(open(new_file_path, mode='rb'))
                    media_file.save()

                    self.assertFalse(os.path.exists(media_old_file_path))

                # Check AudioFile/VideoFile file deletion during object deletion
                media_file_path = media_file.file.path
                self.assertTrue(os.path.exists(media_file_path))
                media_file.delete()
                self.assertFalse(os.path.exists(media_file_path))

        test_crud(AudioFormat, AudioFile, factories.audio_file_factory)
        test_crud(VideoFormat, VideoFile, factories.video_file_factory)

    def test_convert(self):
        """
        Test AudioFile/VideoFile conversation and creation of streams.
        :return:
        """

        def test_media_file_conversion(media_file_cls):

            def mock_save(self, name, content):
                return name

            if issubclass(media_file_cls, VideoFile):
                media_format_set = VideoFormatSet.objects.first()
            else:
                media_format_set = AudioFormatSet.objects.first()

            file_name = 'media_file.{}'.format(media_format_set.formats.first().container)

            with mock.patch.object(FileSystemStorage, 'save', mock_save):
                media_file = mocks.get_mock_media_file(file_name, media_file_cls)

                popen_patcher = mock.patch('subprocess.Popen')
                mock_popen = popen_patcher.start()
                mock_rv = mock.Mock()
                mock_rv.communicate.return_value = [None, None]
                mock_popen.return_value = mock_rv

                mock_file = mock.MagicMock(spec=mock.sentinel.file_spec)
                mock_file.size = 1
                mock_open = mock.MagicMock(return_value=mock_file)

                with mock.patch('avlogue.tasks.open', mock_open):
                    task = media_file.convert(media_format_set)
                    streams = task.get()

                    self.assertTrue(len(streams), media_format_set.formats.count() - 1)
                    stream = streams[0]
                    self.assertEqual(str(stream), "{}: {}".format(str(stream.format), str(media_file)))
                    for stream in streams:
                        self.assertTrue(stream in media_file.streams.all())
                        self.assertIsNotNone(stream.size)

                popen_patcher.stop()

        test_media_file_conversion(AudioFile)
        test_media_file_conversion(VideoFile)

    def test_convert_to_higher_encode_format(self):
        """
        Tests that conversation will be not performed for the higher format.
        :return:
        """
        media_file = mocks.get_mock_media_file('media_file.mp3', AudioFile)
        format_with_higher_bitrate = AudioFormat(
            name='format_with_higher_bitrate',
            audio_bitrate=media_file.bitrate + 1000,
            audio_codec=media_file.audio_codec
        )
        format_with_higher_bitrate.save()
        format_set = AudioFormatSet(name='Test-audio-format-set')
        format_set.save()
        format_set.formats = [format_with_higher_bitrate]

        task = media_file.convert(format_set)
        streams = task.get()
        self.assertEqual(len(streams), 0)
