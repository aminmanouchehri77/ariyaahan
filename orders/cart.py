from decimal import Decimal, InvalidOperation


class CartError(ValueError):
    pass


class Cart:
    SESSION_KEY = 'ariaa_cart'
    MAX_ITEMS = 50
    MAX_QUANTITY = Decimal('1000000')
    QUANTITY_STEP = Decimal('0.001')

    def __init__(self, request):
        self.session = request.session
        self.items = self._load()

    @classmethod
    def parse_quantity(cls, raw):
        try:
            quantity = Decimal(str(raw))
        except (InvalidOperation, TypeError, ValueError):
            raise CartError('مقدار واردشده معتبر نیست.')
        if not quantity.is_finite() or quantity <= 0:
            raise CartError('مقدار باید بیشتر از صفر باشد.')
        if quantity > cls.MAX_QUANTITY:
            raise CartError('مقدار درخواستی بیش از حد مجاز است.')
        if quantity != quantity.quantize(cls.QUANTITY_STEP):
            raise CartError('مقدار را حداکثر با سه رقم اعشار وارد کنید.')
        return quantity

    def _load(self):
        stored = self.session.get(self.SESSION_KEY, {})
        if not isinstance(stored, dict):
            return {}
        normalized = {}
        for key, raw_quantity in stored.items():
            try:
                variant_id = str(int(key))
                quantity = self.parse_quantity(raw_quantity)
            except (CartError, TypeError, ValueError):
                continue
            if len(normalized) < self.MAX_ITEMS:
                normalized[variant_id] = format(quantity, 'f')
        if normalized != stored:
            self.session[self.SESSION_KEY] = normalized
            self.session.modified = True
        return normalized

    def _save(self):
        self.session[self.SESSION_KEY] = self.items
        self.session.modified = True

    def add(self, variant_id, quantity):
        variant_id = str(int(variant_id))
        quantity = self.parse_quantity(quantity)
        current = Decimal(self.items.get(variant_id, '0'))
        combined = current + quantity
        if combined > self.MAX_QUANTITY:
            raise CartError('مجموع مقدار این کالا بیش از حد مجاز است.')
        if variant_id not in self.items and len(self.items) >= self.MAX_ITEMS:
            raise CartError('سبد به بیشترین تعداد ردیف رسیده است.')
        self.items[variant_id] = format(combined, 'f')
        self._save()

    def update(self, variant_id, quantity):
        variant_id = str(int(variant_id))
        if variant_id not in self.items:
            raise CartError('این کالا در سبد نیست.')
        self.items[variant_id] = format(self.parse_quantity(quantity), 'f')
        self._save()

    def remove(self, variant_id):
        self.items.pop(str(variant_id), None)
        self._save()

    def clear(self):
        self.items = {}
        self._save()
