import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0003_remove_pricealert_unique_customer_price_alert_and_more'),
        ('content', '0007_alter_productreview_rating'),
    ]

    operations = [
        migrations.AddField(
            model_name='companyrequest',
            name='profile',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='company_requests', to='accounts.customerprofile', verbose_name='حساب مشتری',
            ),
        ),
        migrations.AddIndex(
            model_name='companyrequest',
            index=models.Index(fields=['profile', 'status', 'created_at'], name='company_req_profile_idx'),
        ),
    ]
