from django.db import migrations


def release_allocations_after_return(apps, schema_editor):
    UnitAllocation = apps.get_model("inventory", "UnitAllocation")
    ReturnRecord = apps.get_model("inventory", "ReturnRecord")
    database = schema_editor.connection.alias

    returned_allocations = ReturnRecord.objects.using(database).filter(
        allocation__released_at__isnull=True,
    ).values_list("allocation_id", "returned_at")

    for allocation_id, returned_at in returned_allocations.iterator():
        UnitAllocation.objects.using(database).filter(
            pk=allocation_id,
            released_at__isnull=True,
        ).update(released_at=returned_at)


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            release_allocations_after_return,
            migrations.RunPython.noop,
        ),
    ]
