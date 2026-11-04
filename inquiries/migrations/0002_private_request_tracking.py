import uuid

import django.db.models.deletion
from django.db import migrations, models


def populate_tracking_ids(apps, schema_editor):
    Inquiry = apps.get_model('inquiries', 'Inquiry')
    database = schema_editor.connection.alias
    batch = []
    for inquiry in Inquiry.objects.using(database).filter(public_id__isnull=True).only('pk').iterator():
        inquiry.public_id = uuid.uuid4()
        batch.append(inquiry)
        if len(batch) >= 500:
            Inquiry.objects.using(database).bulk_update(batch, ('public_id',), batch_size=500)
            batch.clear()
    if batch:
        Inquiry.objects.using(database).bulk_update(batch, ('public_id',), batch_size=500)


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0003_remove_pricealert_unique_customer_price_alert_and_more'),
        ('inquiries', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='inquiry',
            name='public_id',
            field=models.UUIDField(blank=True, editable=False, null=True, verbose_name='شناسهٔ پیگیری'),
        ),
        migrations.RunPython(populate_tracking_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='inquiry',
            name='public_id',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True, verbose_name='شناسهٔ پیگیری'),
        ),
        migrations.AddField(
            model_name='inquiry',
            name='profile',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='inquiries', to='accounts.customerprofile', verbose_name='حساب مشتری',
            ),
        ),
        migrations.AddIndex(
            model_name='inquiry',
            index=models.Index(fields=['profile', 'status', 'created_at'], name='inquiry_profile_status_idx'),
        ),
    ]
