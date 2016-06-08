"""
AVlogue models.
"""

from django.db import models
from django.dispatch import receiver
from django.template.loader import render_to_string
from django.utils.six import python_2_unicode_compatible
from django.utils.timezone import now
from django.utils.translation import ugettext_lazy as _

from avlogue import managers
from avlogue import settings
from avlogue.mime import mimetypes
from avlogue.utils import ContentTypeValidator

video_file_validator = ContentTypeValidator((r'video/.*',), message=_('Only video files are allowed.'))
audio_file_validator = ContentTypeValidator((r'audio/.*',), message=_('Only audio files are allowed.'))


class AudioFields(models.Model):
    """
    Audio fields.
    """
    audio_codec = models.CharField(_('audio codec'), max_length=20,
                                   choices=((name, name) for name in settings.AUDIO_CODECS.keys()))
    audio_bitrate = models.PositiveIntegerField(_('audio bitrate'), null=True, blank=True)
    audio_channels = models.PositiveIntegerField(_('audio channels'), blank=True, null=True)

    class Meta:
        abstract = True


class VideoFields(AudioFields):
    """
    Video fields, also contains audio fields.
    """
    video_codec = models.CharField(_('video codec'), max_length=20,
                                   choices=((name, name) for name in settings.VIDEO_CODECS.keys()))
    video_bitrate = models.PositiveIntegerField(_('video bitrate'), null=True, blank=True)
    video_width = models.IntegerField(_('video width'), blank=True, null=True)
    video_height = models.IntegerField(_('video height'), blank=True, null=True)

    @property
    def resolution(self):
        video_width = self.video_width or ''
        video_height = self.video_height or ''
        if video_width or video_height:
            return '{}x{}'.format(video_width, video_height)

    class Meta:
        abstract = True


class MetaDataFields(models.Model):
    """
    Meta data fields.
    """
    bitrate = models.PositiveIntegerField(_('average file bitrate'))
    duration = models.FloatField(_('duration'))
    size = models.PositiveIntegerField(_('size'))

    class Meta:
        abstract = True


@python_2_unicode_compatible
class BaseFormat(models.Model):
    """
    Base encode format.
    """
    name = models.CharField(_('name'), unique=True, max_length=100)

    def __str__(self):
        return self.name

    class Meta:
        abstract = True


class AudioFormat(BaseFormat, AudioFields):
    """
    Audio encode format.
    """
    container = models.CharField(_('container format'), max_length=10,
                                 choices=((ext, name) for ext, name in settings.AUDIO_CONTAINERS.items()))
    audio_codec_params = models.CharField(_('audio codec params'), max_length=400, blank=True,
                                          help_text=_('Raw options to configure a selected audio codec'))

    class Meta:
        verbose_name = _('audio format')
        verbose_name_plural = _('audio formats')


class VideoFormat(BaseFormat, VideoFields):
    """
    Video encode format.
    """
    container = models.CharField(_('container format'), max_length=10,
                                 choices=((ext, name) for ext, name in settings.VIDEO_CONTAINERS.items()))
    audio_codec_params = models.CharField(_('audio codec params'), max_length=400, blank=True,
                                          help_text=_('Raw options to configure a selected audio codec'))
    video_codec_params = models.CharField(_('video codec params'), max_length=400, blank=True,
                                          help_text=_('Raw options to configure a selected video codec'))
    video_aspect_mode = models.CharField(
        _('video aspect mode'),
        max_length=10,
        choices=(('scale', _('scale')), ('scale_crop', _('scale and crop'))),
        default='scale',
        help_text=_('Aspect mode is only used if both video width and height sizes are specified,'
                    'otherwise aspect mode will be ignored.'))

    class Meta:
        verbose_name = _('video format')
        verbose_name_plural = _('video formats')


@python_2_unicode_compatible
class BaseFormatSet(models.Model):
    name = models.CharField(_('name'), max_length=100, unique=True)

    def __str__(self):
        return self.name

    class Meta:
        abstract = True


class AudioFormatSet(BaseFormatSet):
    """
    Set of audio formats.
    """
    formats = models.ManyToManyField(AudioFormat, verbose_name=_('formats'), related_name='format_sets')


class VideoFormatSet(BaseFormatSet):
    """
    Set of video formats.
    """
    formats = models.ManyToManyField(VideoFormat, verbose_name=_('formats'), related_name='format_sets')


@python_2_unicode_compatible
class MediaFile(MetaDataFields):
    """
    Base media file model.
    """
    title = models.CharField(_('title'), max_length=50, unique=True)
    slug = models.SlugField(_('title slug'), unique=True,
                            help_text=_('A "slug" is a unique URL-friendly title for an object.'))
    description = models.TextField(_('description'), blank=True)
    date_added = models.DateTimeField(_('date published'), default=now)

    def format_has_lower_quality(self, encode_format):
        raise NotImplementedError  # pragma: no cover

    def convert(self, encode_formats):
        """
        Converts media file to specified formats.
        :param encode_formats: list of media file formats
        :return:
        """
        from avlogue import tasks
        encode_formats = list(filter(self.format_has_lower_quality, encode_formats))
        if encode_formats:
            return tasks.encode_media_file.delay(self, encode_formats)

    @property
    def content_type(self):
        return mimetypes.guess_type(self.file.url)[0]

    def html_block(self):
        from avlogue.templatetags.avlogue_tags import avlogue_player
        context = avlogue_player(self)
        return render_to_string('avlogue/player_tag.html', context)

    def __str__(self):
        return self.title

    class Meta:
        abstract = True


class Audio(MediaFile, AudioFields):
    """
    Uploaded audio.
    """
    objects = managers.AudioQuerySet.as_manager()

    file = models.FileField(_('file'), upload_to=settings.AUDIO_DIR, storage=settings.MEDIA_STORAGE,
                            validators=[audio_file_validator])

    def format_has_lower_quality(self, encode_format):
        """
        Return True if encode_format has a lower quality than current audio params.
        :param encode_format:
        :return:
        """
        bitrate = self.audio_bitrate or self.bitrate
        return bitrate >= (encode_format.audio_bitrate or 0)


class Video(MediaFile, VideoFields):
    """
    Uploaded video.
    """
    objects = managers.VideoQuerySet.as_manager()

    file = models.FileField(_('file'), upload_to=settings.VIDEO_DIR, storage=settings.MEDIA_STORAGE,
                            validators=[video_file_validator])

    def format_has_lower_quality(self, encode_format):
        """
        Return True if encode_format has a lower quality than current video params.
        :param encode_format:
        :return:
        """
        audio_bitrate = self.audio_bitrate or self.bitrate
        video_bitrate = self.video_bitrate or self.bitrate

        return audio_bitrate >= (encode_format.audio_bitrate or 0) \
            and video_bitrate >= (encode_format.video_bitrate or 0)


@python_2_unicode_compatible
class BaseStream(MetaDataFields):
    created = models.DateTimeField(_('created'), auto_now=True)

    def __str__(self):
        return "{}: {}".format(str(self.format), str(self.media_file))

    @property
    def content_type(self):
        return mimetypes.guess_type(self.file.url)[0]

    class Meta:
        abstract = True


class AudioStream(BaseStream, AudioFields):
    """
    Audio stream.
    """
    file = models.FileField(_('stream file'), upload_to=settings.AUDIO_STREAMS_DIR,
                            storage=settings.MEDIA_STREAMS_STORAGE)
    media_file = models.ForeignKey(Audio, on_delete=models.CASCADE, related_name='streams')
    format = models.ForeignKey(AudioFormat)

    class Meta:
        unique_together = ['media_file', 'format']


class VideoStream(BaseStream, VideoFields):
    """
    Video stream.
    """
    file = models.FileField(_('stream file'), upload_to=settings.VIDEO_STREAMS_DIR,
                            storage=settings.MEDIA_STREAMS_STORAGE)
    media_file = models.ForeignKey(Video, on_delete=models.CASCADE, related_name='streams')
    format = models.ForeignKey(VideoFormat)

    class Meta:
        unique_together = ['media_file', 'format']


def delete_media_file_on_model_delete(sender, instance, **kwargs):
    """
    Deletes file if object was deleted.
    :param sender:
    :param instance:
    :param kwargs:
    :return:
    """
    if instance.file:
        instance.file.delete(save=False)


def delete_media_old_file_on_model_change(sender, instance, **kwargs):
    """
    Deletes old file if object file has been changed.
    :param sender:
    :param instance:
    :param kwargs:
    :return:
    """
    if instance.pk is None:
        return False
    try:
        old_instance = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        return False

    if not old_instance.file == instance.file:
        old_instance.file.delete(save=False)


# Register media files deletion on model deletion
receiver(models.signals.post_delete, sender=Video)(delete_media_file_on_model_delete)
receiver(models.signals.post_delete, sender=VideoStream)(delete_media_file_on_model_delete)
receiver(models.signals.post_delete, sender=Audio)(delete_media_file_on_model_delete)
receiver(models.signals.post_delete, sender=AudioStream)(delete_media_file_on_model_delete)

# Register media files deletion on model changing
receiver(models.signals.pre_save, sender=Video)(delete_media_old_file_on_model_change)
receiver(models.signals.pre_save, sender=VideoStream)(delete_media_old_file_on_model_change)
receiver(models.signals.pre_save, sender=Audio)(delete_media_old_file_on_model_change)
receiver(models.signals.pre_save, sender=AudioStream)(delete_media_old_file_on_model_change)
