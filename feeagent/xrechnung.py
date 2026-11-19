"""FEE-Agent xrechnung – Rechnung als Factur-X (ZUGFeRD) XML (EN16931-Profil)."""
from xml.sax.saxutils import escape


def factur_x(rechnung: dict, verkäufer: dict, käufer: dict) -> str:
    """Minimal valides Factur-X XML (Profil EN16931)."""
    pos_xml = ""
    for i, p in enumerate(rechnung["positionen"], start=1):
        minuten = p["minuten"]
        betrag = round(minuten / 60 * rechnung["stundensatz"], 2)
        pos_xml += f"""<rsm:LineItem>
<ram:LineID>{i}</ram:LineID>
<ram:SpecifiedTradeProduct><ram:Name>Rechtsberatung</ram:Name></ram:SpecifiedTradeProduct>
<ram:BilledQuantity unitCode="MIN">{minuten}</ram:BilledQuantity>
<ram:NetPriceProductTradePrice><ram:ChargeAmount>{rechnung['stundensatz']:.2f}</ram:ChargeAmount></ram:NetPriceProductTradePrice>
<ram:LineTotalAmount>{betrag:.2f}</ram:LineTotalAmount>
<ram:SpecifiedTradeAllowanceCharge><ram:ChargeIndicator>false</ram:ChargeIndicator>
<ram:ActualAmount>0.00</ram:ActualAmount></ram:SpecifiedTradeAllowanceCharge>
</rsm:LineItem>"""
    ust = round(rechnung["betrag"] * 0.19 / 1.19, 2)
    netto = round(rechnung["betrag"] - ust, 2)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
 xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100">
<rsm:ExchangedDocument><ram:ID>{escape(rechnung['nummer'])}</ram:ID>
<ram:IssueDateTime><udt:DateTimeString>{rechnung['datum']}</udt:DateTimeString></ram:IssueDateTime>
</rsm:ExchangedDocument>
<rsm:SupplyChainTradeTransaction>
{pos_xml}
<ram:SpecifiedTradeSettlementHeaderMonetarySummation>
<ram:LineTotalAmount>{rechnung['betrag']:.2f}</ram:LineTotalAmount>
<ram:TaxBasisTotalAmount>{netto:.2f}</ram:TaxBasisTotalAmount>
<ram:TaxTotalAmount currencyID="EUR">{ust:.2f}</ram:TaxTotalAmount>
<ram:GrandTotalAmount>{rechnung['betrag']:.2f}</ram:GrandTotalAmount>
</ram:SpecifiedTradeSettlementHeaderMonetarySummation>
</rsm:SupplyChainTradeTransaction>
<rsm:SpecifiedSupplyChainTradeAgreement>
<ram:SellerTradeParty><ram:Name>{escape(verkäufer['name'])}</ram:Name></ram:SellerTradeParty>
<ram:BuyerTradeParty><ram:Name>{escape(käufer['name'])}</ram:Name></ram:BuyerTradeParty>
</rsm:SpecifiedSupplyChainTradeAgreement>
</rsm:CrossIndustryInvoice>"""
