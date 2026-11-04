import uuid

import django.db.models.deletion
from django.db import migrations, models


def populate_tracking_ids(apps, schema_editor):
    MarketplaceListing = apps.get_model('marketplace', 'MarketplaceListing')
    database = schema_editor.connection.alias
    batch = []
    for listing in MarketplaceListing.objects.using(database).filter(public_id__isnull=True).only('pk').iterator():
        listing.public_id = uuid.uuid4()
        batch.append(listing)
        if len(batch) >= 500:
            MarketplaceListing.objects.using(database).bulk_update(batch, ('public_id',), batch_size=500)
            batch.clear()
    if batch:
        MarketplaceListing.objects.using(database).bulk_update(batch, ('public_id',), batch_size=500)


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0003_remove_pricealert_unique_customer_price_alert_and_more'),
        ('marketplace', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='marketplacelisting',
            name='public_id',
            field=models.UUIDField(blank=True, editable=False, null=True, verbose_name='شناسهٔ پیگیری'),
        ),
        migrations.RunPython(populate_tracking_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='marketplacelisting',
            name='public_id',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True, verbose_name='شناسهٔ پیگیری'),
        ),
        migrations.AddField(
            model_name='marketplacelisting',
            name='profile',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='marketplace_listings', to='accounts.customerprofile', verbose_name='حساب ثبت‌کننده',
            ),
        ),
        migrations.AddIndex(
            model_name='marketplacelisting',
            index=models.Index(fields=['profile', 'status', 'created_at'], name='market_profile_status_idx'),
        ),
    ]
