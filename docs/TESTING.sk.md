# Čo otestovať v programe

Zoznam toho, čo treba po každej etape prejsť ručne. Odškrtni, čo sedí, a napíš mi, čo nie.

## Etapa 5 — klientske PDF (verzia 0.6.0)

Stiahni si build z [desktop-latest](https://github.com/metjus/Calculator/releases/tag/desktop-latest),
rozbaľ do nového priečinka a prekopíruj k nemu svoj starý priečinok `data`.

### Nastavenia

- [ ] **Logo** — nahraj PNG, JPEG, SVG alebo WebP do 1 MB. Má sa ukázať náhľad a tlačidlá *Replace* a *Remove*.
- [ ] Súbor väčší než 1 MB alebo iný typ (napr. `.txt`) má byť odmietnutý zrozumiteľnou hláškou.
- [ ] **Tvoje údaje** — meno, IČO, telefón, e-mail. Idú do pätičky obálky aj do QR vizitky.

### Obrazovka Client PDF

- [ ] V audite klikni na web so skóre → **Create PDF**. Pri weboch bez skóre tlačidlo nie je.
- [ ] Prepni jazyk **SK / ČS / EN** — texty problémov aj nadpisy sa musia zmeniť všetky.
- [ ] Nechaj **názov firmy** prázdny → na obálke má byť doména. Vypíš ho → má byť v hlavičke.
- [ ] Prepíš **úvodný odstavec** a sleduj, či sa do pol sekundy objaví v náhľade vpravo.
- [ ] Odškrtni pár problémov → počet aj náhľad sa musia zmeniť (aj počet strán hore vpravo).
- [ ] Presuň problém **šípkami ↑ ↓** → v náhľade sa má presunúť aj poradie čísel.
- [ ] Vypíš **tri ceny**, vyber rádiovkou, ktorá možnosť je „Odporúčam".
- [ ] **Export PDF** → súbor sa stiahne a pomenuje podľa domény.

### Samotné PDF

- [ ] Obálka: logo, názov firmy, dátum po slovensky, veľké skóre s pásikom a verdikt s bodkou.
- [ ] Problémy: pri každom *Čo je zle / Čo to spôsobuje / Riešenie*, vykanie, žiadne vymyslené čísla.
- [ ] Screenshoty počítača aj telefónu.
- [ ] Porovnanie s konkurenciou, ak si ju pri audite zadal.
- [ ] Posledná strana: tri možnosti so správnymi cenami, zvýraznená tá odporúčaná, veta
      „Ak chcete riešiť len niektoré veci…" a **nikde žiadny rozpis po položkách**.
- [ ] **Naskenuj QR kód telefónom** → má ponúknuť uloženie kontaktu s tvojím menom, telefónom a e-mailom.
- [ ] Otvor PDF **bez internetu** — musí sa zobraziť celé vrátane písma a obrázkov.

### Po exporte

- [ ] Spusti druhý export → **ceny majú byť predvyplnené** tie, čo si zadal naposledy.

## Etapa 7 — CRM (verzia 0.7.0)

### Zoznam zákazníkov

- [ ] **Customers** — hore počty (spolu / otvorených / čaká na teba), lievik, konverzia a donut podľa stavu.
- [ ] **Follow up** — v zozname majú byť tí, čo čakajú na odpoveď dlhšie než 7 dní, a tí s dátumom
      ďalšieho kroku na dnes alebo skôr. Klik na meno otvorí kartu.
- [ ] Filtre **stav / projekt / má web** a vyhľadávanie sa dajú kombinovať.
- [ ] Klik na stĺpec v lieviku prefiltruje tabuľku; druhý klik filter zruší.
- [ ] **Add customer** — pridaj firmu **bez webu**. Má dostať stav „Lead (no website)" a objaviť sa
      vo filtri „No website (lead)".

### Karta zákazníka

- [ ] Klikni na stav v riadku → uloží sa a objaví sa v časovej osi s dátumom.
- [ ] Pri stave **Deal** sa zobrazí pole na dohodnutú cenu; po uložení sa pripočíta do „Agreed".
- [ ] **Log a contact** — vyber spôsob (osobne / telefón / e-mail / správa) a napíš poznámku.
      Pri prvom kontakte sa stav sám prepne na „Contacted".
- [ ] Časová os ukazuje aj **audity** — klik na *Open* otvorí detail webu.
- [ ] Koš pri zázname ho vymaže (audit sa vymazať nedá).
- [ ] **Next step** + dátum → zákazník sa v deň splatnosti objaví v zozname Follow up.
- [ ] **Design demo** — vlož odkaz. Po 30 dňoch má karta hore upozorniť, že ukážku treba stiahnuť.
- [ ] Leadovi bez webu dopíš **Website** → stav sa zmení na „Audited" a dá sa auditovať.
- [ ] **Delete notes** zmaže poznámky, ale nechá firmu, web, dátumy a výsledky auditov.
- [ ] **Delete, keep the address** nechá adresu označenú „do not contact".

### Čo zatiaľ nie je

- PDF „Čo by vám web priniesol" pre firmy bez webu — potrebuje vlastný návrh a texty.
- Archív, automatické presuny a mazanie po čase (etapa 8).
- Kontrola duplicít je v API, ale zatiaľ bez obrazovky.
