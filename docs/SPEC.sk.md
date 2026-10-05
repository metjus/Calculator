# Zadanie pre Claude Code: Nástroj na audit webov

## Účel a princípy

Postav lokálny desktopový program, ktorý skontroluje weby firiem, ohodnotí ich, vytvorí presvedčivý PDF audit a pomôže mi sledovať oslovených zákazníkov. Najprv ho používam sám na získavanie zákaziek (oprava webov a nové weby), neskôr ho chcem predávať ďalším webdizajnérom.

- **Vstup sú len URL, ktoré zadám ja.** Program nezbiera kontakty ani dáta o firmách z katalógov, máp či vyhľadávačov. Kontaktné údaje (mená, telefóny, e-maily) program neukladá vôbec, hľadám ich vždy ručne na webe firmy.
- **Ohľaduplné skenovanie:** rešpektuj robots.txt, rozumné tempo požiadaviek, časový limit na každý web, ukladaj len výsledky auditu, nie celé stránky.
- **Kvalita na úrovni hotového produktu:** moderný dizajn, intuitívne ovládanie, svetlý aj tmavý režim, žiadne pády pri chybe jedného webu.
- **Rozhranie programu v angličtine,** výstupy pre klientov v zvolenom jazyku (SK, CZ, EN).

## Architektúra

Skenovacie jadro musí byť úplne oddelené od rozhrania, aby som ho neskôr mohol použiť vo webovej SaaS verzii bez prepisovania.

- **Jadro (Python balík):** skenovanie, kontroly, skóre, AI posudok, generovanie PDF. Žiadna závislosť na GUI. Ovládateľné aj z príkazového riadku a pripravené na budúce API.
- **Desktopové rozhranie:** PySide6 alebo CustomTkinter (vyber a zdôvodni). Skenovanie beží na pozadí, okno vždy reaguje.
- **Dáta:** lokálna databáza SQLite (zákazníci, audity, história, nastavenia).
- **Screenshoty a PDF:** Playwright.
- **Externé služby:** Google PageSpeed Insights API, Anthropic API (Claude) na posudok dizajnu a kontrolu cien.
- **Konfigurácia:** váhy skóre, ceny a texty v samostatných upraviteľných súboroch (JSON), nie natvrdo v kóde.
- **Distribúcia:** na konci zabalenie do .exe cez PyInstaller.

## Vstup a kontroly

Program prijme jednu URL, zoznam URL alebo CSV a skontroluje každý web v nasledujúcich oblastiach.

**Vstup (CSV):** url, nazov\_firmy (voliteľné), konkurencia (voliteľné, URL oddelené čiarkou), projekt (napr. „Kaderníctva Trnava“).

**Kontroly:**

- **Základ:** dostupnosť, HTTPS, platnosť SSL, presmerovanie http → https.
- **Mobil:** viewport, veľkosť písma, veľkosť tlačidiel, vodorovné posúvanie.
- **Rýchlosť:** PageSpeed skóre pre mobil aj desktop, Core Web Vitals, príliš veľké obrázky.
- **SEO:** title, meta popis, H1, alt texty, sitemap, Open Graph náhľad, favicon, štruktúrované dáta LocalBusiness.
- **Dôvera a obsah:** viditeľný kontakt, klikateľný telefón, adresa a mapa, rok v pätičke, funkčné odkazy na sociálne siete, cookie lišta, rozbité odkazy.
- **Technika:** CMS a jeho verzia, zastarané knižnice, chyby v konzole, zmiešaný HTTP/HTTPS obsah.
- **Prístupnosť:** kontrast, popisy obrázkov, popisy formulárových polí.
- **Dizajn, automaticky:** znaky zastaranosti (pevná šírka, tabuľkové rozloženie, drobné písmo, priveľa fontov).
- **Dizajn, AI (voliteľné):** screenshot desktopu a mobilu pošli Claudovi; výstup skóre 1–10 a 2–3 konkrétne postrehy. Najprv čo funguje, potom čo je zle a čo to spôsobuje.
- **Porovnanie s konkurenciou:** ak sú zadané URL konkurentov, oskenuj ich rovnako a priprav porovnanie.

**Cookie lišty:** pred screenshotom sa pokús lištu zavrieť (bežné tlačidlá „Prijať“, „Súhlasím“, „Accept“, „Odmietnuť“). Ak sa to nepodarí, zaznač to v logu.

**Blokované weby:** ak web skenovanie odmietne alebo ukáže ochrannú stránku, zisti, či ide pravdepodobne o Cloudflare (hlavičky cf-ray, server: cloudflare, challenge stránka). Web označ „Pravdepodobne chránený Cloudflare – skontroluj ručne“, nezapočítavaj ho do skóre ani grafov a v dashboarde ho ukáž zvlášť.

## Vyhľadávanie firiem

Program vie sám nájsť firmy podľa odboru a oblasti; ja z výsledkov vyberiem, ktoré idú do auditu alebo CRM.

**Zdroje (kombinácia)**

- **Google Places API:** hlavné pokrytie. Ukladaj natrvalo len place\_id; názov, adresu a web načítaj podľa place\_id znova, keď ich potrebujem (karta zákazníka, export PDF).
- **OpenStreetMap (Overpass API):** doplnkový bezplatný zdroj; dáta sa smú ukladať (uveď zdroj podľa licencie ODbL).
- Výsledky z oboch zdrojov zlúč a odstráň duplicity (podľa domény webu, názvu a polohy).
- Z oboch zdrojov ber len názov, polohu, odbor a web. Žiadne telefóny, e-maily ani mená.

**Zadanie oblasti**

- Výber krajiny bez predvolenej hodnoty; hľadanie sa nespustí, kým krajinu nevyberiem. Krajina obmedzí hľadanie, takže „Trnava“ nikdy nenájde českú obec.
- Pole „Mesto alebo obec“ s našepkávaním, ktoré ukáže celý názov, napr. „Trnava, Trnavský kraj, Slovensko“. Pri rovnakých názvoch si vyberiem správnu.
- Polomer v km (posuvník, napr. 5–50 km), alternatívne celý okres alebo kraj.
- Náhľad oblasti na mape s vyznačeným kruhom.
- Uloženie oblasti a odboru ako šablóny (napr. „Autoservisy Galanta + 15 km“).

**Odbor**

- Zoznam bežných odborov (kaderníctvo, autoservis, reštaurácia, stavebná firma…) namapovaný na typy Google a značky OpenStreetMap, plus voľné textové vyhľadávanie.

**Výsledky**

- Zoznam rozdelený na „Má web“ a „Bez webu“, s počtami.
- Pri každej firme označenie, ak už je v databáze (status a dátum posledného kontaktu) alebo má značku „Do not contact“.
- Zaškrtnutím vyberiem firmy a pošlem ich do auditu alebo ako „Bez webu“ do CRM.
- V nastaveniach pole na Google Places API kľúč (môže byť rovnaký Google Cloud kľúč ako pre PageSpeed, ak sú obe API povolené) s odkazom na návod a tlačidlom „Test key“.
- Odhad nákladov na vyhľadávanie pred spustením; upozornenie pri prekročení mesačného bezplatného limitu.

## Skóre

Každý web dostane celkové skóre 0–100 a kategóriu: Kritický, Slabý, OK, Dobrý.

- Váhy jednotlivých kontrol a hranice kategórií sú v konfiguračnom súbore, aby som ich mohol ladiť.
- Najväčšiu váhu majú veci s priamym dopadom na zákazníkov: mobil, funkčnosť, dôvera a kontakt, rýchlosť.
- Ak sa AI posudok dizajnu nepoužije, skóre sa prepočíta bez neho.
- Web, ktorý sa nepodarilo načítať, nemá skóre, len stav „nenačítané“ s dôvodom.

## Dizajn programu

Program má pôsobiť ako hotový komerčný produkt, nie ako skript s oknom; pred písaním kódu rozhrania mi ukáž návrh.

**Rozloženie**

- Ľavý bočný panel s navigáciou: Dashboard, Vyhľadávanie, Audity, Zákazníci, Nastavenia. Počet čakajúcich pripomienok ako odznak pri položke Zákazníci.
- Hlavná plocha s nadpisom sekcie, akciami vpravo hore a obsahom v kartách.
- Rozumné prispôsobenie veľkosti okna (od notebooku po veľký monitor), minimálna veľkosť okna.

**Vizuálny štýl**

- Čistý, moderný, veľa priestoru, jedna výrazná akcentová farba, inak neutrálne tóny.
- Svetlý a tmavý režim s prepínačom, oba plnohodnotne navrhnuté.
- Jedna dobre čitateľná písmová rodina, jasná hierarchia nadpisov a čísel.
- Jednotná sada ikon (napr. Lucide), žiadne emoji ikony.
- Bez generických AI klišé: žiadne fialovo-modré gradienty, prehnané tiene ani sklenené efekty.

**Dashboard a grafy**

- Horný rad metrík ako karty s veľkým číslom a malým popisom.
- Grafy v jednotnej palete; farby kategórií a statusov sa líšia aj svetlosťou, nielen odtieňom. Pri donutoch číslo v strede, popisky čitateľné.
- Tabuľky s prehľadnými riadkami, farebným štítkom skóre a statusu, triedením a filtrami nad tabuľkou.
- Prázdne stavy s vysvetlením a tlačidlom ďalšieho kroku (napr. „Zatiaľ žiadne audity – spusti prvý“).

**PDF audit**

- Profesionálny a vzdušný, v štýle programu, s mojím logom, ak je zadané.
- Čitateľný aj vytlačený čiernobielo.

**Postup**

Navrhni 2–3 vizuálne smery (akcentová farba, písmo, celkový dojem) ako mockup hlavnej obrazovky dashboardu, ja vyberiem a až potom pokračuj.

## Rozhranie

Program má tri hlavné časti: nastavenia, spustenie auditu s viditeľným priebehom a dashboard so zákazníkmi.

**Nastavenia**

- Pole „Google PageSpeed API key“ a pod ním odkaz na návod, ako kľúč získať: https://developers.google.com/speed/docs/insights/v5/get-started
- Pole „Claude API key“ a pod ním odkaz na Anthropic Console: https://console.anthropic.com/settings/keys (over aktuálnosť oboch odkazov).
- Pri každom kľúči tlačidlo „Test key“ s výsledkom platný / neplatný. Kľúče skryté (••••) s možnosťou zobrazenia, uložené lokálne.
- Ak kľúč chýba, program jasne povie, čo doplniť, a nespadne.
- Moje údaje do PDF: meno, IČO, telefón, e-mail, logo (voliteľné).
- Predvolený jazyk PDF, ceny opráv, pravidlá pripomienok a archívu (viď ďalšie sekcie).

**Spustenie auditu**

- Výber CSV alebo vloženie URL, názov projektu.
- Checkbox „Evaluate design with Claude (AI)“: neaktívny bez Claude kľúča; pri zaškrtnutí odhad ceny pre aktuálny počet webov.
- Tlačidlá „Start audit“ a počas behu „Stop“.

**Priebeh auditu**

- Celkový progress bar „Web 3 of 20“.
- Aktuálny web a krok, napr. „kadernictvo-x.sk: taking mobile screenshot“.
- Živý log s časom: ✔ hotovo, ⚠ upozornenie, ✖ chyba.
- Chyba na jednom webe nezastaví celý audit.
- Na konci zhrnutie (počet webov, chyby, trvanie) a tlačidlá „Open dashboard“ a „Open PDF folder“.

## Výstupy

Každý audit vytvorí záznam v dashboarde, screenshoty a PDF pre klienta v zvolenom jazyku.

**Dashboard auditov** (beží v programe, nie ako statický súbor)

- Metriky: počet auditovaných webov, priemerné skóre, počet kritických, počet bez HTTPS.
- Donut grafy: kategórie skóre, HTTPS áno/nie, mobil áno/nie, CMS (max 5 výsekov + „ostatné“).
- Stĺpcový graf najčastejších problémov.
- Tabuľka webov od najhoršieho skóre s filtrami (projekt, kategória, status) a vyhľadávaním.
- Samostatný zoznam webov chránených Cloudflare alebo nenačítaných.
- Detail webu: skóre, problémy, screenshoty, AI posudok, porovnanie s konkurenciou.

**Screenshoty:** desktop aj mobil pre každý web aj konkurenciu.

**PDF audit**

- Výber jazyka pred exportom: slovenčina, čeština, angličtina.
- Úvod s názvom firmy a celkovým hodnotením.
- Screenshoty desktopu a mobilu.
- Nájdené problémy zoradené podľa dopadu na zákazníka (štruktúra textov v sekcii Texty problémov).
- Porovnanie s konkurenciou, ak je zadaná.
- Posledná strana s ponukou (sekcia Ceny a ponuka).
- Moje meno, IČO, telefón, e-mail a QR kód s mojím kontaktom (vCard). Žiadne portfólio.
- Pred exportom náhľad, kde upravím ceny, odporúčanie a vyhodím položky.

## Texty problémov a tón

Každý problém v PDF má tri časti a znie ľudsky: čo je zle, čo to spôsobuje, ako sa to dá vyriešiť.

1. **Čo je zle:** jedna veta bez technického žargónu.
2. **Čo to spôsobuje:** dopad na zákazníkov a firmu.
3. **Riešenie:** krátky popis opravy, bez ceny.

Príklad: „Web sa zle zobrazuje na mobile. Text je drobný a stránku treba približovať. Väčšina ľudí dnes hľadá firmy cez telefón; keď sa im stránka zle číta, často ju zavrú a skúsia konkurenciu.“

- Texty pre všetky typy problémov v súbore texty.json pre SK, CZ, EN, upraviteľné bez zásahu do kódu.
- Vykanie klientovi, priamy a konštruktívny tón, nikdy urážlivý.
- Opatrné formulácie („môže“, „často“, „mnohí“), žiadne vymyslené čísla ani percentá.
- AI posudok dizajnu v rovnakom tóne a štruktúre.

## Ceny a ponuka

Ceny opráv sú uložené natrvalo v programe, program z nich navrhne cenu a ja ju pred exportom ručne potvrdím. Žiadne mesačné služby, len jednorazové opravy alebo nový web.

**Ceny v nastaveniach**

- Ku každému typu problému cena opravy a cena „Nový web od X €“.
- Pri audite sa kvôli cenám nevolá žiadne API.
- Program zobrazí len pre mňa rozpis po položkách a odporúčaný súčet.

**Posledná strana PDF: tri možnosti**

1. **Oprava najdôležitejšieho problému:** program navrhne, ktorý to je; vstupná, lacnejšia možnosť.
2. **Oprava všetkých nájdených problémov:** odporúčaná, vizuálne zvýraznená.
3. **Nový web od X €:** s vetou „Návrh hlavnej stránky vám pripravím zadarmo, rozhodnete sa až potom.“

Pod možnosťami: „Ak chcete riešiť len niektoré veci, ozvite sa a dohodneme sa.“ Rozpis cien po položkách sa v PDF nezobrazuje. Pravidlo odporúčania (napr. nízke skóre dizajnu alebo vysoký súčet opráv → nový web) je nastaviteľné.

**Kontrola cien**

- Tlačidlo „Check my prices“: jedno volanie Claude API, porovnanie moja cena / odhad trhovej ceny pre SK alebo CZ / rozdiel, jasne označené ako odhad.
- Nič sa neprepíše samo, každú zmenu potvrdzujem po položkách.
- Pod tlačidlom „Last checked: \[dátum\]“.
- Ak od poslednej kontroly prešlo viac ako 90 dní, pri spustení nenápadné upozornenie.

## Správa zákazníkov

Dashboard slúži aj ako jednoduchý predajný systém: kto je v akom stave, kedy som sa ozval a koho treba kontaktovať.

**Karta zákazníka**

- Firma, URL, projekt, poznámky. Žiadne polia na kontaktnú osobu, telefón ani e-mail.
- Pridanie ručne alebo z auditu, úprava, mazanie (sekcia Archív a mazanie).
- Časová os: audit, kontakty, zmeny statusu, návrh, zákazka.
- „Ďalší krok“: dátum a čo urobiť.

**Statusy** (každá zmena sa uloží s dátumom)

Auditovaný → Oslovený → Čaká na vyjadrenie → Má záujem → Návrh poslaný → Zákazka. Mimo lievika: Nemá záujem, Neozval sa.

**História kontaktov:** dátum, spôsob (osobne, telefón, e-mail, správa) a krátka poznámka.

**Pripomienky**

- Zoznam „Follow up“: zákazníci v stave „Čaká na vyjadrenie“ dlhšie ako X dní (predvolene 7) a tí s dátumom ďalšieho kroku dnes alebo skôr.
- Návrh dizajnu: odkaz na živú ukážku a dátum odoslania; upozornenie po 30 dňoch, že ukážku treba stiahnuť (aj keď sa klient neozval).

**Grafy a metriky**

- Lievik statusov ako stĺpcový graf.
- Úspešnosť: oslovení → majú záujem → zákazka, v %.
- Oslovenia a zákazky po týždňoch, čiarový graf.
- Priemerný čas od oslovenia po odpoveď.
- Súčet dohodnutých cien zákaziek (cenu zadám pri statuse „Zákazka“).
- Donut: rozdelenie zákazníkov podľa statusu.

Statusy farebne odlíšené tak, aby sa farby líšili aj svetlosťou. Filtre podľa statusu, projektu, dátumu a „Má web / Bez webu“, ktoré sa dajú navzájom kombinovať, a vyhľadávanie.

## Firmy bez webu

Firmy bez webu sú leady na nový web, preto ich program eviduje rovnako ako ostatné, len bez auditu.

- Zákazníka viem pridať bez URL; dostane označenie „Bez webu“ a v dashboarde vlastný filter a počítadlo.
- Pri importe CSV riadok bez URL nevyhodí chybu, ale vytvorí firmu „Bez webu“.
- Namiesto auditu vytvorí PDF „Čo by vám web priniesol“: prečo ľudia hľadajú firmy online, porovnanie s konkurenciou z rovnakého odboru a mesta, ktorá web má (ak je zadaná), a ponuka nového webu s návrhom hlavnej stránky zadarmo.
- Rovnaký tón a jazyky ako pri audite, žiadne vymyslené čísla.
- Ak firma neskôr web získa, doplním URL a môžem ju normálne auditovať.

## Archív a mazanie

Žiadny zákazník sa nikdy nemaže automaticky; starí zákazníci sa len presunú do archívu, aby som vedel, koho som už oslovil.

- **Archív:** stavy „Nemá záujem“, „Neozval sa“ a „Zákazka“ sa po X mesiacoch (predvolene 3) presunú do archívu. Archív sa dá prehľadávať a zákazníka viem vrátiť späť.
- **Kontrola duplicít** pri pridaní aj pri importe CSV (porovnávaj doménu a názov firmy): „Túto firmu si už oslovil \[dátum\], status: \[status\].“
- **Osloviť znova:** po X mesiacoch (predvolene 12) od odmietnutia ponúkni zákazníka v samostatnom zozname.
- **Ochrana údajov:** po X rokoch (predvolene 2) v archíve vymaž poznámky; ponechaj firmu, URL, dátumy a výsledok. Pred vymazaním ma upozorni.
- **Ručné mazanie v karte zákazníka**, obe s potvrdením:
  - „Delete notes“: zmaže poznámky; ponechá firmu, URL, dátumy, výsledok.
  - „Delete company completely“: zmaže všetko vrátane histórie, screenshotov a PDF; voliteľne ponechá len URL so značkou „Do not contact“.
- Firmy so značkou „Do not contact“ program pri importe alebo pridaní jasne označí a bez môjho potvrdenia ich neauditujem.

## Súbory a zálohy

Všetky dáta programu sú v jednom priečinku, ktorý sa dá celý presunúť na iný počítač.

- Databáza, nastavenia, texty, screenshoty a PDF v jednom priečinku; jeho umiestnenie sa dá zmeniť v nastaveniach.
- Pri spustení automatická záloha databázy, uchovať posledných 10 záloh. Záloha nič nemaže, len chráni pred stratou dát.
- V nastaveniach tlačidlo „Open data folder“.
- API kľúče nikdy v súbore, ktorý by mohol skončiť v Gite; pridaj ich do .gitignore.

## Etapy stavby

Stavaj po etapách a po každej mi ukáž výsledok, kým pôjdeš ďalej.

1. **Jadro:** sken jedného webu, všetky kontroly okrem AI, skóre, výpis výsledkov v príkazovom riadku.
2. **Hromadný sken + okno:** výber vizuálneho smeru (sekcia Dizajn programu), import CSV, vyhľadávanie firiem podľa odboru a oblasti, nastavenia s API kľúčmi, priebeh auditu, cookie lišty, Cloudflare detekcia.
3. **Dashboard auditov:** SQLite, metriky, grafy, tabuľka, detail webu.
4. **Screenshoty a AI posudok dizajnu:** vrátane checkboxu a odhadu ceny, porovnanie s konkurenciou.
5. **PDF audit:** tri jazyky, texty problémov, ponuka s tromi možnosťami, náhľad pred exportom, QR s kontaktom.
6. **Ceny:** nastavenia cien, rozpis, kontrola cien cez Claude, 90-dňové upozornenie.
7. **Správa zákazníkov:** karty, statusy, história, pripomienky, grafy predaja, firmy bez webu.
8. **Archív a mazanie:** archív, duplicity, osloviť znova, ochrana údajov, zálohy.
9. **Finalizácia:** vyladenie dizajnu, testy na reálnych weboch, zabalenie do .exe cez PyInstaller.
