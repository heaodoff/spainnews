"""Test all 5 categories through the full pipeline: AI → approval → admin buttons."""
import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])

from database import init_db
from translator import process_article, check_needs_approval
from bot import send_for_approval

# Test articles — one per category, all designed to be FULL + need approval
TEST_ARTICLES = [
    {
        "title": "Spain introduces new 100% tax on property purchases by non-EU residents",
        "summary": (
            "The Spanish government has approved a new law that will impose a 100% tax surcharge "
            "on residential property purchases by non-EU buyers. The measure, which takes effect "
            "on July 1, 2026, aims to curb speculative investment and improve housing affordability "
            "for residents. Properties valued under €500,000 in tourist zones will be exempt. "
            "The tax applies to both new and resale properties. Real estate industry groups have "
            "criticized the move, saying it will deter foreign investment. The government says "
            "the law is necessary to protect local housing markets."
        ),
        "source": "El País",
        "url": "https://elpais.com/test-property-tax-2026",
        "category": "real_estate",
        "image_url": "",
    },
    {
        "title": "Modelo 720: Spain extends deadline for foreign asset declarations to September 2026",
        "summary": (
            "Spain's tax agency (AEAT) has announced that the deadline for Modelo 720 foreign "
            "asset declarations has been extended from March 31 to September 30, 2026. The "
            "extension applies to all tax residents who hold assets abroad worth over €50,000. "
            "The decision follows a European Court ruling that found Spain's previous penalty "
            "regime disproportionate. New penalties are capped at €1,500. Taxpayers who filed "
            "late in previous years may request refunds of excessive fines. Tax advisors recommend "
            "filing early to avoid system overload."
        ),
        "source": "Cinco Días",
        "url": "https://cincodias.com/test-modelo-720-extension",
        "category": "finance",
        "image_url": "",
    },
    {
        "title": "Spain launches new digital nomad visa portal with 48-hour processing",
        "summary": (
            "The Spanish immigration office has launched a new online portal for digital nomad "
            "visa applications, promising processing times of just 48 hours. The portal supports "
            "applications in English, Spanish, and French. Applicants must prove monthly income "
            "of at least €3,000 and employment with a non-Spanish company. The visa is valid "
            "for 3 years with the option to convert to permanent residency. Since its introduction "
            "in 2023, over 15,000 digital nomad visas have been issued. The new portal also "
            "handles renewals and family member applications."
        ),
        "source": "La Vanguardia",
        "url": "https://lavanguardia.com/test-digital-nomad-portal",
        "category": "expats",
        "image_url": "",
    },
    {
        "title": "New rental law in Spain: landlords must register all contracts in national registry by June 2026",
        "summary": (
            "Spain's Congress has passed a new housing law requiring all landlords to register "
            "rental contracts in a national digital registry by June 30, 2026. Unregistered "
            "contracts will not be legally enforceable, and landlords face fines of up to €10,000. "
            "The registry will be used to enforce rent caps in 'stressed housing zones.' Tenants "
            "can verify their contract status online. The law also introduces a mandatory energy "
            "efficiency certificate for all rental properties. Landlord associations warn of "
            "administrative burden for small property owners."
        ),
        "source": "El Mundo",
        "url": "https://elmundo.es/test-rental-registry-law",
        "category": "legislation",
        "image_url": "",
    },
    {
        "title": "Supermarket prices in Spain rise 8% as new packaging tax takes effect",
        "summary": (
            "The Spanish government's new packaging tax has led to an average 8% increase in "
            "supermarket prices across the country, according to consumer group OCU. The tax, "
            "which charges €0.45 per kilogram of non-reusable plastic packaging, has been passed "
            "on to consumers by major chains including Mercadona, Carrefour, and Lidl. Basic goods "
            "such as milk, yogurt, and bottled water are most affected. The tax is projected to "
            "raise €724 million annually. Consumer groups are calling for exemptions on essential "
            "food items. Meanwhile, reusable container stations are being piloted in 200 stores."
        ),
        "source": "20 Minutos",
        "url": "https://20minutos.es/test-packaging-tax-prices",
        "category": "economy",
        "image_url": "",
    },
]


async def run_tests():
    init_db()
    print("\n" + "=" * 60)
    print("ТЕСТ ВСЕХ КАТЕГОРИЙ — 5 статей → AI → approval flow")
    print("=" * 60 + "\n")

    for i, article in enumerate(TEST_ARTICLES, 1):
        print(f"\n{'─' * 50}")
        print(f"[{i}/5] {article['title'][:70]}...")
        print(f"      Источник: {article['source']}")
        print(f"{'─' * 50}")

        # Step 1: AI editorial pipeline
        processed = process_article(article)
        if not processed:
            print("  ⚠️  AI решил SKIP — пропуск")
            continue

        print(f"  ✅ Score: {processed.get('score')}")
        print(f"  ✅ Format: {processed['format']}")
        print(f"  ✅ Category: {processed['category']}")
        print(f"  ✅ Image desc: {processed.get('image_description', '')[:80]}...")

        # Step 2: Approval check
        approval = check_needs_approval(article, processed)
        print(f"  ✅ Needs approval: {approval['needs_approval']}")
        print(f"  ✅ Recommendation: {approval['recommendation']}")
        print(f"  ✅ Suggest service: {approval['suggest_service']}")
        if approval.get('cta_text'):
            print(f"  ✅ CTA: {approval['cta_text'][:60]}")

        # Step 3: Send for approval (all go through approval for testing)
        pid = await send_for_approval(processed, approval, urgent=False)
        print(f"  📤 Sent for approval: #{pid}")

        # Small delay between posts
        await asyncio.sleep(2)

    print("\n" + "=" * 60)
    print("Все 5 статей отправлены на согласование!")
    print("Нажми кнопки в Telegram:")
    print("  ✅ Опубликовать — без услуги")
    print("  ✅ + Услуга — с CTA и Stripe кнопкой")
    print("  ✏️ Без услуги — убрать предложенную услугу")
    print("  ❌ Отклонить — не публиковать")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(run_tests())
