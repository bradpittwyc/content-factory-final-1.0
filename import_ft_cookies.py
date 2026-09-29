# -*- coding: utf-8 -*-
"""
Convert Netscape Cookie format to Playwright storage_state.json and test FT scraping.
"""
import json
import time
import httpx
from pathlib import Path

COOKIE_TEXT = """
.ft.com	TRUE	/	FALSE	1825206956	FTClientSessionId	376442ae-15e9-472d-9a65-afe408520d14
.ft.com	TRUE	/	FALSE	1822182956	spoor-id	376442ae-15e9-472d-9a65-afe408520d14
.ft.com	TRUE	/	TRUE	1824774956	_cb	BORcKmD-zsAt2K2AM
.www.ft.com	TRUE	/	TRUE	1806371758	__exponea_etc__	001d7ea4-eb58-4355-b3a3-84a97f0112e3
.www.ft.com	TRUE	/	TRUE	1806371757	__exponea_time2__	0.30431270599365234
.ft.com	TRUE	/	TRUE	1799980425	FTCookieConsentGDPR	true
.ft.com	TRUE	/	TRUE	1807549920	consentDate	2026-04-12T17:11:59.646Z
.ft.com	TRUE	/	FALSE	1819354903	skipPasskeySetup	false
.ft.com	TRUE	/	TRUE	1809710137	_twpid	tw.1776014136602.422004909750721460
.ft.com	TRUE	/	FALSE	1807596947	zit.data.toexclude	0
.ft.com	TRUE	/	FALSE	1799112292	FTCookieConsentSync	false
.ft.com	TRUE	/	FALSE	1811728331	next-edition	international
.ft.com	TRUE	/	TRUE	1812847328	consentDateUsnat	2026-06-13T00:42:07.592Z
.ft.com	TRUE	/	FALSE	1817600442	_ga	GA1.2.516787883.1782969819
.ft.com	TRUE	/	FALSE	1817600443	_ga_NTY0HBYF35	GS2.2.s1783040368$o2$g1$t1783040442$j60$l0$h0
.ft.com	TRUE	/	FALSE	1815265542	EXP_71c1f5ad26_identity	JTIyJTdCJTVDJTIyd2ViX2V4cF9pZF92MiU1QyUyMiUzQSU1QyUyMjRlMmIwYmE4LTM0MzAtNGIxOC1iNzgzLWI4YjJmMWE0YjVlOSU1QyUyMiUyQyU1QyUyMmZpcnN0X3NlZW4lNUMlMjIlM0ElNUMlMjIxNzc2MTAwNzY2LjA0MiU1QyUyMiU3RCUyMg==
.ft.com	TRUE	/	FALSE	1818642790	AppUser	{"eid":1%2C"email":""%2C"entitlements":[{"name":"askFtEnabled"%2C"value":{"asBool":true}}%2C{"name":"giftArticleAllowance"%2C"value":[]}]%2C"isEligibleForUpgrade":false%2C"isIneligibleForInAppPurchase":true%2C"level":"premium"%2C"name":"a%20Premium%20user"%2C"upgradeEligibilityTerm":""%2C"username":"An%20FT%20Premium%20user"%2C"uuid":"60897ebf-13ee-4f2f-a291-b49198c0aefc"%2C"signature":"P0aZl5F46Wd8TvYS6WpnH4nplns6osUm89hHLwLQXhmxtIycUMG\%2FdwfIIOA51wHOdBKmX8mi8qRWP4LqZFVmnA=="%2C"key":"v1"}
.ft.com	TRUE	/	FALSE	1806285355	FTConsent	behaviouraladsOnsite%3Aon%2CcookiesOnsite%3Aon%2CcookiesUseraccept%3Aon%2CdemographicadsOnsite%3Aon%2CenhancementByemail%3Aon%2CenhancementByfax%3Aoff%2CenhancementByphonecall%3Aoff%2CenhancementBypost%3Aoff%2CenhancementBysms%3Aoff%2CmarketingByemail%3Aon%2CmarketingByfax%3Aoff%2CmarketingByphonecall%3Aoff%2CmarketingBypost%3Aoff%2CmarketingBysms%3Aoff%2CmembergetmemberByemail%3Aoff%2CpermutiveadsOnsite%3Aon%2CpersonalisedmarketingOnsite%3Aon%2CprogrammaticadsOnsite%3Aon%2CrecommendedcontentOnsite%3Aon
.ft.com	TRUE	/	TRUE	1819354487	usnatUUID	98ba4f0c-5c91-4656-9b15-271407f76b6e_138
.ft.com	TRUE	/	TRUE	1803716493	FTSession_s	048eR9BAm0sf05srsskIStAL0wAAAaBCT2PAw8I.MEMCH22X2Cl3SzzPMzdImtsb8tEiPejrsODVMliGkR67YpoCIEKUEzCC2UJA0DPdsc57tYXWhXcuVOYRUHb1Kj4wi6Jx
.ft.com	TRUE	/	TRUE	1806285358	permutive-id	c12a533f-17e2-4312-8785-d3daf85de8d1
.ft.com	TRUE	/	TRUE	1795737856	_rdt_uuid	1776013933161.2d0e4136-0d31-4662-800e-3b5acf23742a
.ft.com	TRUE	/	TRUE	1795737856	_rdt_em	:602900e9cc6f116bf33e5e9598ed9aa88cfda496656e18b680e447f2d87cc75f,98893a7420e99f9a317cb249ebc20aa7c5e3f26ef26a5f5a9758e93fbb07dfc3
.ft.com	TRUE	/	TRUE	1795737856	_rdt_pn	:175~a52b4a845ecda2efacedaf3f96ef49cc4d8547528a7904056c60a7be9e0844fd
.ft.com	TRUE	/	TRUE	1820017864	consentUUID	95bde8d3-153e-464b-a26e-af872b2581b9_58
.ft.com	TRUE	/	FALSE	1792536201	_sanba	0
.ft.com	TRUE	/	FALSE	1792624096	_sxh	2125,2126,2127,2133,2134,2136,2137,2138,2140,2143,2149,2150,2151,
.ft.com	TRUE	/	FALSE	1821568100	_sxo	{"R":1,"tP":5366,"tM":21,"sP":1,"sM":0,"dP":161,"dM":0,"dS":1,"tS":83,"cPs":10,"lPs":[80,10,30,80,80],"sSr":80,"sWids":[],"wN":0,"cdT":0,"F":13,"RF":3,"w":0,"SFreq":17,"last_wid":0,"bid":1036,"accNo":"","clientId":"","isEmailAud":0,"isPanelAud":0,"hDW":0,"isRegAud":0,"isExAud":0,"isDropoff":0,"devT":0,"exPW":0,"Nba":-1,"userName":"","dataLayer":"","localSt":"","emailId":"","emailTag":"","subTag":"","lVd":"2026-9-21","oS":"376442ae-15e9-472d-9a65-afe408520d14","cPu":"https://www.ft.com/content/90714056-d364-43d9-9411-9bde92f966b3","pspv":1,"pslv":566,"pssSr":80,"pswN":0,"psdS":0,"pscdT":0,"RP":0,"TPrice":0,"ML":"","isReCaptchaOn":false,"reCaptchaSiteKey":"","reCaptchaSecretKey":"","extRefer":"","dM2":0,"tM2":0,"sM2":0,"RA":3,"ToBlock":-1,"CC":null,"groupName":null}
.ft.com	TRUE	/	FALSE	1822141346	_clck	hj99ae%5E2%5Eg9u%5E1%5E2462
.ft.com	TRUE	/	FALSE	1790693940	_uetsid	06c80d10bb4811f1a2c55167b7d8ed69
.ft.com	TRUE	/	FALSE	1824303540	_uetvid	c0028360369211f19a1cef549ea6cfbf
.ft.com	TRUE	/	FALSE	1790713317	_clsk	1cdc456%5E1790626917822%5E1%5E1%5Eg.clarity.ms%2Fcollect
.www.ft.com	TRUE	/	FALSE	1790713317	_clsk	1cdc456%5E1790626917822%5E1%5E1%5Eg.clarity.ms%2Fcollect
www.ft.com	FALSE	/	FALSE	1790713317	_clsk	1cdc456%5E1790626917822%5E1%5E1%5Eg.clarity.ms%2Fcollect
.ft.com	TRUE	/	FALSE	1790648756	OriginalReferer	None
.ft.com	TRUE	/	FALSE	1790648756	FtComEntryPoint	/
.www.ft.com	TRUE	/	TRUE	1790648756	__cf_bm	_oT0vreDoBXxkyyAwojdMg_qFfBwb7pVWpNQKsGvMTE-1790646955.7647274-1.0.1.1-DqOw_jrnz5P9qQO5oja7zufwVmDMHyDpWqQ6nHh_cmjdkUzspvYKQb9Lkzjp0T.UtBHqmmsH4YLgfOBuMefD_jd8XbsYyF7FTVse0mgMA0jenHSieTi3hfLG6s2rbKOj
.ft.com	TRUE	/	TRUE	1824774956	_chartbeat2	.1776013888267.1790646956583.1001001110000011.CPI2hP7kDMez486aBvTd59DvevuK.1
.ft.com	TRUE	/	TRUE	1790648756	_cb_svref	external
.ft.com	TRUE	/	FALSE	1791858620	_gcl_au	1.1.954330550.1784082620.-.-.1787818892.889779336.1790605344.1790646962
www.ft.com	FALSE	/	FALSE	1790647262	dicbo_id	%7B%22dicbo_fetch%22%3A1790646962531%7D
.ft.com	TRUE	/	TRUE	1809795514	__gads	ID=66c215905f39bede:T=1776099514:RT=1790646976:S=ALNI_MbveA3W1I9jVpHoeLmTwLhACZE2Gw
.ft.com	TRUE	/	TRUE	1791651514	__eoi	ID=81a209af3c578e8f:T=1776099514:RT=1790646976:S=AA-AfjZ2mJKRlZv1Qj5Zz9spvetk
.ft.com	TRUE	/	TRUE	1824343095	_twsid	1790646961978-767980261.11.1790647094830
.www.ft.com	TRUE	/	TRUE	1820598830	cf_clearance	NOWn6of8BzYZD_pnC_3G4z7Hujftgq9_JXsVGsaO5vk-1789062832-1.2.1.1-ZTL8JpT1PG1.G4glc00njYQbq4qRSKeSD9yOfFfSKuO40AalbguXzJdaXQ52Hi3uPjMxdFSIFewS4hjiIeLbhRpbuOiA5q8b1DWeoLepssk0hi0mhcam.d1Z_r5odzg3uAfWMNH.i_iTnF_EwYGyTfAkggQq8eXr3edWgDtOnffs7ENYwADzDU5Uxsgmv_dSDmjqUN8Uy6ZD7UYUoV.UC2Y7bCPJpTU1nyDQTUxw2vfn6L1w4J2DyayiF.vX4fC2we8xpW9OLKLICuOCWdniKPJj6HC2cZla_nVbT18Ucx8VqlGdIMZrDpjfHFjGBdUs34Ng2Yhk8eOYj3wtra6jq9USPLnbZCcvwL2CnncTc38Og_W4XC3oDSVm1iT22MI9.4ymjYjhzzFPTxmzTE_rNQJOYoWsqifqsIn7Umq2CQ8iYXuqeAkHA_hZRs.lrtMqfpVmjF7Y8079NC8kHy.7SfHMPFasgC1KMco6Kpw0GeGTvDU2EaawMYAebkkQPb8FbQFbtcnRLpEyM1bsNSCHLA
"""

def parse_netscape_cookies(text):
    cookies = []
    for line in text.strip().split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split('\t')
        if len(parts) >= 7:
            domain, flag, path, secure, expiration, name, value = parts[:7]
            cookies.append({
                "name": name,
                "value": value,
                "domain": domain,
                "path": path,
                "expires": float(expiration) if expiration.isdigit() else -1,
                "httpOnly": False,
                "secure": secure.upper() == "TRUE",
                "sameSite": "Lax"
            })
    return cookies

def save_storage_state():
    cookies = parse_netscape_cookies(COOKIE_TEXT)
    state = {
        "cookies": cookies,
        "origins": []
    }
    session_path = Path("ft_session.json")
    session_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {len(cookies)} cookies to {session_path.resolve()}")

if __name__ == "__main__":
    save_storage_state()
