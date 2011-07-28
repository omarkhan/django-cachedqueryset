django-cachedqueryset
=====================

This module provides a django QuerySet subclass that attempts to filter in-memory, without hitting the database. This is useful in cases where a dataset is accessed multiple times in a view via related objects: rather than querying the database once for each related object, pull the entire table into memory and filter from there.

## Usage ##

Use CacheManager as the default manager for the models you wish to filter in memory:

```python
from cachedqueryset import CacheManager

class MyModel(models.Model):
    objects = CacheManager()
```

Then, in your view, use the `load_cache` method to load all objects into memory:

```python
def my_view(request):
    MyModel.objects.load_cache()
```

## Warning ##

This is rough around the edges and could use some proper testing. Feel free to contribute ;)

## Licence ##

Copyright © 2011 Omar Khan, released under the MIT licence.
