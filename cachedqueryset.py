import operator
from django.db.models.sql.constants import *
from django.core.exceptions import FieldError
from django.db import models
from django.core.signals import request_finished
from django.dispatch import receiver


class CachedQuerySet(models.query.QuerySet):
    """
    QuerySet subclass that attempts to do as much processing as possible
    in memory, without hitting the database. This is achieved by:
    
    a) Allowing for a prepopulated cache (passed to __init__)

    b) Filtering in memory and copying the results into the cache
       of the new queryset
    """
    resolver = {
        'exact': operator.eq,
        'iexact': lambda a, b: a.lower() == b.lower(),
        'gt': operator.gt,
        'gte': operator.ge,
        'lt': operator.lt,
        'lte': operator.le,
        'contains': operator.contains, # for strings
        'icontains': lambda a, b: b.lower() in a.lower(),
        'in': lambda a, b: a in b, # for lists
        'startswith': lambda a, b: a.startswith(b),
        'istartswith': lambda a, b: a.lower().startswith(b.lower()),
        'endswith': lambda a, b: a.endswith(b),
        'iendswith': lambda a, b: a.lower().endswith(b.lower()),
        'range': lambda a, b: b[0] <= a <= b[1],
        'year': lambda a, b: a.year == b,
        'month': lambda a, b: a.month == b,
        'day': lambda a, b: a.day == b,
        'is_null': lambda a, b: (not a and b) or (a and not b),
    }

    def __init__(self, model=None, query=None, using=None, cache=None):
        super(CachedQuerySet, self).__init__(model, query, using)
        self._result_cache = cache

    def _clean_lookups(self, filters):
        """
        Returns None if filters includes lookups spanning multiple
        relationships, otherwise returs a list of (field_name, value,
        lookup_type) 3-tuples.
        
        Foreign key 'model__field' filters are modified to read 'model_field'
        to allow for in-memory filtering
        """
        lookups = []
        for arg, value in filters.iteritems():
            # code from django.db.models.sql.Query.addfilter method
            parts = arg.split(LOOKUP_SEP)
            if not parts:
                raise FieldError("Cannot parse keyword query %r" % arg)
            
            # Work out the lookup type and remove it from 'parts', if necessary.
            if len(parts) == 1 or parts[-1] not in QUERY_TERMS:
                lookup_type = 'exact'
            else:
                lookup_type = parts.pop()
            
            if lookup_type not in self.resolver: # Unsupported lookup type
                return None
            if len(parts) > 2: # Spans multiple relationships, not supported
                return None
            elif len(parts) == 2: # ForeignKey field, swap __ with _
                lookups.append(('%s_%s' % (parts[0], parts[1]), value, lookup_type))
            else:
                lookups.append((parts[0], value, lookup_type))
        return lookups

    def using(self, alias):
        qs = super(CachedQuerySet, self).using(alias)
        if self._result_cache is not None and alias == self._db: # Same db, copy cache
            qs._result_cache = [obj for obj in self._result_cache]
        return qs
    
    def _filter_or_exclude(self, negate, *args, **kwargs):
        qs = super(CachedQuerySet, self)._filter_or_exclude(negate, *args, **kwargs)
        if self._result_cache is not None:
            lookups = self._clean_lookups(kwargs)
            if lookups:
                new_cache = list(self._result_cache)
                for attr, value, lookup_type in lookups:
                    if negate:
                        new_cache = [obj for obj in new_cache
                                     if not self.resolver[lookup_type](getattr(obj, attr), value)]
                    else:
                        new_cache = [obj for obj in new_cache
                                     if self.resolver[lookup_type](getattr(obj, attr), value)]
                qs._result_cache = new_cache
        return qs

    def order_by(self, *field_names):
        qs = super(CachedQuerySet, self).order_by(*field_names)
        if self._result_cache is not None:
            qs._result_cache = [obj for obj in self._result_cache]
            for field in field_names:
                qs._result_cache.sort(key=lambda obj: getattr(obj, field))
        return qs


class CacheManager(models.Manager):
    """
    This manager class allows models to cache their results
    """
    use_for_related_fields = True

    _cache = {}

    def get_cache(self):
        return self._cache[self.model]

    def set_cache(self, value):
        self._cache[self.model] = value

    def del_cache(self):
        del self._cache[self.value]

    cache = property(get_cache, set_cache, del_cache)

    def load_cache(self):
        """
        Initialises the cache with the full set of objects
        """
        qs = super(CacheManager, self).get_query_set()
        self.cache = list(qs)

    def get_query_set(self):
        if self.model in self._cache:
            return CachedQuerySet(self.model, using=self.db,
                                  cache=self._cache.get(self.model))
        else:
            return super(CacheManager, self).get_query_set()


@receiver(request_finished)
def empty_cache(sender, **kwargs):
    """
    Always empty the cache after the request has finished, so as not
    to break the next request
    """
    CacheManager._cache = {}
