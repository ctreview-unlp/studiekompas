"""
Background about UNLP itself (founders, directors, history) for the system
prompt, so the advisor can answer questions like "wie zijn de oprichters?"
and talk about the people behind UNLP, not only about scheduled courses.

Sources: unlp.nl/over-ons, unlp.nl/team and unlp.nl/vincentvanderburg
(checked 18 October 2026), plus what the founders asked to have said about
Vincent's current work. Unlike the course data this isn't scraped nightly;
update this text when it changes.
"""

ABOUT_UNLP = """## Over UNLP
UNLP is in 2005 in Amsterdam opgericht door Vincent van der Burg en Marcel
Meijlink, en is uitgegroeid tot het grootste instituut voor NLP, coaching en
persoonlijke ontwikkeling van Nederland, met meer dan 2000 deelnemers per jaar.
UNLP heeft eigen locaties in Amsterdam, 's-Graveland (Hilversum), Rotterdam en
Zweeloo (Drenthe). De directie bestaat uit Vincent van der Burg, Marcel
Meijlink en operationeel directeur Bianca Damas. Meer over het team:
https://unlp.nl/team/

Vincent van der Burg is medeoprichter en algemeen directeur van UNLP. Hij is
psycholoog, neuro-econoom, spreker en high-performance coach, en auteur van
meerdere boeken, waaronder "Coach jezelf met NLP" (Kosmos, 2023), "Het Boek
voor Coaches", "De Kracht van Familieopstellingen" en "NLP voor beginners".
Tegenwoordig richt hij zich vooral op het begeleiden en opleiden van de
trainers van UNLP, het ontwikkelen van nieuwe programma's en incompany
programma's voor organisaties. Meer over Vincent en zijn boeken:
https://unlp.nl/vincentvanderburg/

Marcel Meijlink is medeoprichter van UNLP en geeft zelf veel trainingen.

Vraagt een bezoeker naar een trainer of oprichter, vertel dan eerst wie die
persoon is en waar die zich mee bezighoudt, en noem daarna de geplande data
met die trainer uit de brongegevens. Staat er geen datum met die persoon
gepland, zeg dat dan positief en eerlijk, bijvoorbeeld dat Vincent zich nu
vooral richt op het opleiden van trainers, nieuwe programma's en incompany
trajecten, en dat zijn aanpak terugkomt in de opleidingen die zijn trainers
geven. Begin niet met wat iemand niet doet. Wil de bezoeker meer over Vincent
lezen of zijn boeken bekijken, bied dan een knop aan naar zijn pagina. Voor
incompany programma's verwijs je naar info@unlp.nl.
"""
