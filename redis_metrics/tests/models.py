"""
This file demonstrates writing tests using the unittest module. These will pass
when you run "manage.py test".

Replace this with more appropriate tests for your application.
"""
from datetime import date, datetime
from mock import call, patch, Mock

from django.conf import settings
from django.test import TestCase

from ..models import R


class TestR(TestCase):
    """Tests for the ``R`` class."""

    def setUp(self):
        self.old_host = getattr(settings, 'REDIS_METRICS_HOST', 'localhost')
        self.old_port = getattr(settings, 'REDIS_METRICS_PORT', 6379)
        self.old_db = getattr(settings, 'REDIS_METRICS_DB', 0)
        settings.REDIS_METRICS_HOST = 'localhost'
        settings.REDIS_METRICS_PORT = 6379
        settings.REDIS_METRICS_DB = 0

        # The redis client instance on R is a MagicMock object
        with patch('redis_metrics.models.redis'):
            self.r = R()
            self.redis = self.r.r  # keep a sanely named reference to Redis

    def tearDown(self):
        settings.REDIS_METRICS_HOST = self.old_host
        settings.REDIS_METRICS_PORT = self.old_port
        settings.REDIS_METRICS_DB = self.old_db
        super(TestR, self).tearDown()

    def test__init__(self):
        """Test creation of an R object with parameters."""
        with patch('redis_metrics.models.redis.StrictRedis') as mock_redis:
            kwargs = {
                'metric_slugs_key': 'MSK',
                'gauge_slugs_key': 'GSK',
                'host': 'HOST',
                'port': 'PORT',
                'db': 'DB'
            }
            inst = R(**kwargs)
            self.assertEqual(inst.host, "HOST")
            self.assertEqual(inst.port, "PORT")
            self.assertEqual(inst.db, "DB")
            self.assertEqual(inst._metric_slugs_key, "MSK")
            self.assertEqual(inst._gauge_slugs_key, "GSK")
            mock_redis.assert_called_once_with(
                host='HOST', port='PORT', db='DB')

    def test__date_range(self):
        """Tests ``R._date_range``."""

        # Verify that omitting the ``since`` parameter gives you dates for the
        # previous year.
        dates = [d for d in self.r._date_range()]
        self.assertEqual(len(dates), 365)

        # Provide a ``since`` parameter.
        t = datetime(2012, 12, 25)  # Merry Christmas!
        # NOTE: just check for dates, ignoring hours, mins, seconds, etc.
        dates = [d.date() for d in self.r._date_range(since=t)]

        self.assertIn(t.date(), dates)  # Should include our specified date
        self.assertGreater(len(dates), 1)  # There should be some dates

    def test__category_key(self):
        """Creates a redis key for a given category string."""
        self.assertEqual(
            self.r._category_key("Sample Category"),
            u"c:Sample Category"
        )

    def test__category_slugs(self):
        """Verify that this returns an empty list or a list of slugs."""
        # When there are no results from redis
        with patch('redis_metrics.models.redis.StrictRedis') as mock_redis:
            mock_redis.return_value.get.return_value = None
            r = R()
            result = r._category_slugs("Sample Category")
            self.assertEqual(result, [])

        # When there are no results from redis
        with patch('redis_metrics.models.redis.StrictRedis') as mock_redis:
            mock_redis.return_value.get.return_value = '["slug-a", "slug-b"]'
            r = R()
            result = r._category_slugs("Sample Category")
            self.assertEqual(result, ['slug-a', 'slug-b'])

    @patch.object(R, '_category_slugs')
    def test__categorize(self, mock_category_slugs):
        """Categorizing a slug should add the correct key/values to Redis"""

        # Sample category and metric slug
        cat = "Sample Category"
        cat_key = "c:Sample Category"
        slug = "sample-slug"

        with patch('redis_metrics.models.redis.StrictRedis') as mock_redis:
            redis_instance = mock_redis.return_value
            r = R()

            # When there are no existing slugs for a category
            mock_category_slugs.return_value = []
            r._categorize(slug, cat)
            mock_category_slugs.assert_called_once_with(cat)
            json_slug = '["{0}"]'.format(slug)
            redis_instance.set.assert_called_once_with(cat_key, json_slug)

            redis_instance.reset_mock()
            mock_category_slugs.reset_mock()

            # When there's an existing slug for a category
            mock_category_slugs.return_value = ["existing-slug"]
            r._categorize(slug, cat)
            mock_category_slugs.assert_called_once_with(cat)
            json_slug = '["{0}", "existing-slug"]'.format(slug)
            redis_instance.set.assert_called_once_with(cat_key, json_slug)

            redis_instance.reset_mock()
            mock_category_slugs.reset_mock()

            # When we're setting a duplicate metric (should be no duplicates
            # in the list that's set in Redis
            mock_category_slugs.return_value = [slug]
            r._categorize(slug, cat)
            mock_category_slugs.assert_called_once_with(cat)
            json_slug = '["{0}"]'.format(slug)
            redis_instance.set.assert_called_once_with(cat_key, json_slug)

    def test__build_keys(self):
        """Tests ``R._build_keys``. with default arguments."""
        d = date.today()
        slug = 'test-slug'
        expected_results = [
            "m:{0}:{1}".format(slug, d.strftime("%Y-%m-%d")),
            "m:{0}:w:{1}".format(slug, d.strftime("%Y-%U")),
            "m:{0}:m:{1}".format(slug, d.strftime("%Y-%m")),
            "m:{0}:y:{1}".format(slug, d.strftime("%Y")),
        ]
        keys = self.r._build_keys(slug)
        self.assertEqual(keys, expected_results)

    def test__build_keys_daily(self):
        """Tests ``R._build_keys``. with a *daily* granularity."""
        d = date(2012, 4, 1)  # April Fools!
        keys = self.r._build_keys('test-slug', date=d, granularity='daily')
        self.assertEqual(keys, ['m:test-slug:2012-04-01'])

    def test__build_keys_weekly(self):
        """Tests ``R._build_keys``. with a *weekly* granularity."""
        d = date(2012, 4, 1)  # April Fools!
        keys = self.r._build_keys('test-slug', date=d, granularity='weekly')
        self.assertEqual(keys, ['m:test-slug:w:2012-14'])

    def test__build_keys_monthly(self):
        """Tests ``R._build_keys``. with a *monthly* granularity."""
        d = date(2012, 4, 1)  # April Fools!
        keys = self.r._build_keys('test-slug', date=d, granularity='monthly')
        self.assertEqual(keys, ['m:test-slug:m:2012-04'])

    def test__build_keys_yearly(self):
        """Tests ``R._build_keys``. with a *yearly* granularity."""
        d = date(2012, 4, 1)  # April Fools!
        keys = self.r._build_keys('test-slug', date=d, granularity='yearly')
        self.assertEqual(keys, ['m:test-slug:y:2012'])

    def test_metric_slugs(self):
        """Test that ``R.metric_slugs`` makes a call to Redis SMEMBERS."""
        self.r.metric_slugs()
        self.redis.assert_has_calls([call.smembers(self.r._metric_slugs_key)])

    def test_metric(self):
        """Test setting metrics using ``R.metric``."""

        slug = 'test-metric'
        n = 1

        # get the keys used for the metric, so we can check for the appropriate
        # calls
        day, week, month, year = self.r._build_keys(slug)
        self.r.metric(slug, num=n)

        # Verify that setting a metric adds the appropriate slugs to the keys
        # set and then incrememts each key
        self.redis.assert_has_calls([
            call.sadd(self.r._metric_slugs_key, day, week, month, year),
            call.incr(day, n),
            call.incr(week, n),
            call.incr(month, n),
            call.incr(year, n),
        ])

    @patch.object(R, '_categorize')
    def test_metric_with_category(self, mock_categorize):
        """The ``metric`` method should call ``_categorize`` if passed a
        ``category`` argument."""
        category = "Some Category"
        slug = 'categorized-metric'
        n = 1

        # get the keys used for the metric, so we can check for calls
        day, week, month, year = self.r._build_keys(slug)
        self.r.metric(slug, num=n, category=category)

        # Verify that setting a metric adds the appropriate slugs to the keys
        # set and then incrememts each key
        self.redis.assert_has_calls([
            call.sadd(self.r._metric_slugs_key, day, week, month, year),
            call.incr(day, n),
            call.incr(week, n),
            call.incr(month, n),
            call.incr(year, n),
        ])

        # Make sure this gets categorized.
        mock_categorize.assert_called_once_with(slug, category)

    def test_get_metric(self):
        """Tests getting a single metric; ``R.get_metric``."""
        slug = 'test-metric'
        self.r.get_metric(slug)

        # Verify that we GET the keys from redis
        day, week, month, year = self.r._build_keys(slug)
        self.redis.assert_has_calls([
            call.get(day),
            call.get(week),
            call.get(month),
            call.get(year),
        ])

    def test_get_metrics(self):

        # Slugs for metrics we want
        slugs = ['metric-1', 'metric-2']

        # Build the various keys for each metric
        keys = []
        for s in slugs:
            day, week, month, year = self.r._build_keys(s)
            keys.extend([day, week, month, year])

        # construct the calls to redis
        calls = [call.get(k) for k in keys]

        # Test our method
        self.r.get_metrics(slugs)
        self.redis.assert_has_calls(calls)

    def test_get_category_metrics(self):
        """returns metrics for a given category"""
        r = R()
        # Mock methods called by `get_category_metrics`
        r._category_slugs = Mock(return_value=['some-slug'])
        r.get_metrics = Mock(return_value="RESULT")
        results = r.get_category_metrics("Sample Category")
        self.assertEqual(results, 'RESULT')
        r._category_slugs.assert_called_once_with("Sample Category")
        r.get_metrics.assert_called_once_with(['some-slug'])

    def _metric_history_keys(self, slugs, since=None, granularity='daily'):
        """generates the same list of keys used in ``get_metric_history``.
        These can then be used to test for calls to redis. Note: This is
        duplicate code from ``get_metric_history`` :-/ """
        if type(slugs) != list:
            slugs = [slugs]
        keys = set()
        for slug in slugs:
            for date in self.r._date_range(since):
                keys.update(set(self.r._build_keys(slug, date, granularity)))
        return keys

    def _test_get_metric_history(self, slugs, granularity):
        """actual test code for ``R.get_metric_history``."""
        keys = self._metric_history_keys(slugs, granularity=granularity)
        self.r.get_metric_history(slugs, granularity=granularity)
        self.redis.assert_has_calls([call.mget(keys)])

    def test_get_metric_history_daily(self):
        """Tests ``R.get_metric_history`` with daily granularity."""
        self._test_get_metric_history('test-slug', 'daily')

    def test_get_metric_history_weekly(self):
        """Tests ``R.get_metric_history`` with weekly granularity."""
        self._test_get_metric_history('test-slug', 'weekly')

    def test_get_metric_history_monthly(self):
        """Tests ``R.get_metric_history`` with monthly granularity."""
        self._test_get_metric_history('test-slug', 'monthly')

    def test_get_metric_history_yearly(self):
        """Tests ``R.get_metric_history`` with yearly granularity."""
        self._test_get_metric_history('test-slug', 'yearly')

    def test_get_metric_multiple_history_daily(self):
        self._test_get_metric_history(['foo', 'bar'], 'daily')

    def test_get_metric_multiple_history_weekly(self):
        self._test_get_metric_history(['foo', 'bar'], 'weekly')

    def test_get_metric_multiple_history_monthly(self):
        self._test_get_metric_history(['foo', 'bar'], 'monthly')

    def test_get_metric_multiple_history_yearly(self):
        self._test_get_metric_history(['foo', 'bar'], 'yearly')

    @patch.object(R, 'get_metric_history')
    def test_get_metric_history_as_columns(self, mock_metric_hist):
        # set up some sample (yearly) metrics
        mock_metric_hist.return_value = [
            ("m:bar:y:2012", '1'),
            ('m:bar:y:2013', '2'),
            ('m:foo:y:2012', '3'),
            ('m:foo:y:2013', '4'),
        ]
        expected_results = [
            ('Period',  'foo',  'bar'),
            ('y:2012',  '3',    '1'),
            ('y:2013',  '4',    '2'),
        ]
        with patch('redis_metrics.models.redis.StrictRedis'):
            r = R()
            kwargs = {
                'slugs': ['foo', 'bar'],
                'since': None,
                'granularity': 'yearly',
            }
            results = r.get_metric_history_as_columns(**kwargs)
            self.assertEqual(results, expected_results)

    def _test_get_metric_history_as_columns(self, slugs, granularity):
        """Test that R.get_metric_history_as_columns makes calls to the
        following functions:

        * ``R.r.mget``
        * ``R.get_metric_history``
        * ``templatetags.metric_slug``
        * ``templatetags.strip_metric_prefix``

        """
        keys = self._metric_history_keys(slugs, granularity=granularity)
        self.r.get_metric_history_as_columns(slugs, granularity=granularity)

        # Verifies the correct call to redis
        self.redis.assert_has_calls([call.mget(keys)])

        # Verify that the method gets called correctly
        with patch('redis_metrics.models.R') as mock_r:
            r = mock_r.return_value  # Get an instance of our Mocked R class
            r.get_metric_history_as_columns(slugs, granularity=granularity)
            mock_r.assert_has_calls([
                call().get_metric_history_as_columns(slugs,
                                                     granularity=granularity)
            ])

    def test_get_metric_history_as_columns_daily(self):
        self._test_get_metric_history_as_columns(['foo', 'bar'], 'daily')

    def test_get_metric_history_as_columns_weekly(self):
        self._test_get_metric_history_as_columns(['foo', 'bar'], 'weekly')

    def test_get_metric_history_as_columns_monthly(self):
        self._test_get_metric_history_as_columns(['foo', 'bar'], 'monthly')

    def test_get_metric_history_as_columns_yearly(self):
        self._test_get_metric_history_as_columns(['foo', 'bar'], 'yearly')

    def test_gauge_slugs(self):
        """Tests that ``R.gauge_slugs`` calls the SMEMBERS command."""
        self.r.gauge_slugs()
        self.redis.assert_has_calls([call.smembers(self.r._gauge_slugs_key)])

    def test__gauge_key(self):
        """Tests that ``R._gauge_key`` correctly generates gauge keys."""
        key = self.r._gauge_key('test-gauge')
        self.assertEqual(key, 'g:test-gauge')

    def test_gauge(self):
        """Tests setting a gauge with ``R.gauge``. Verifies that the gauge slug
        is added to the set of gauge slugs and that the value gets set."""
        self.r.gauge('test-gauge', 9000)
        self.redis.assert_has_calls([
            call.sadd(self.r._gauge_slugs_key, 'g:test-gauge'),
            call.set('g:test-gauge', 9000),
        ])

    def test_get_gauge(self):
        """Tests retrieving a gague with ``R.get_gauge``. Verifies that the
        Redis GET command is called with the correct key."""
        self.r.get_gauge('test-gauge')
        self.redis.assert_has_calls([call.get('g:test-gauge')])