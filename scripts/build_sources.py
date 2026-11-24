"""Build data/sources.yaml from reviewed rows. Only `official_read` rows may have gate_default=per_rules."""
import yaml,pathlib
D='2026-11-24'
# id|tier|status|topics|hosts|license_model|license_id|attr|commercial|derivatives|ai_use|trust|verify|terms_url|notes
R='''
nasa_images|T1|active|space_science|images-api.nasa.gov,images-assets.nasa.gov|public_domain_agency|NASA-media|yes|yes|yes|unknown|A|official_read|https://www.nasa.gov/nasa-brand-center/images-and-media/|third-party items marked; no endorsement; identifiable persons need permission commercially
nasa_svs|T1|degraded|space_science|svs.gsfc.nasa.gov|public_domain_agency|PD-unless-noted|no|yes|yes|unknown|A|official_read|https://svs.gsfc.nasa.gov/help/|terms read 2026-11-20; connection failed twice 2026-11-24; licensed music is not PD
ia|T1|active|history_archive|archive.org|per_item|per_item|per_item|per_item|per_item|per_item|B|official_read|https://archive.org/about/terms|Prelinger items with an explicit CC licenseurl only, always third-party WARN; terms dated 2014-12-31 read in a browser 2026-11-23: declared licence may be used to the extent the declarer is trusted
ia_nasa|T1|active|space_science|archive.org|per_item|per_item|per_item|per_item|per_item|per_item|B|probed|https://archive.org/about/terms|same adapter as ia
loc|T1|active|history_archive|www.loc.gov,tile.loc.gov|per_item|per_item|per_item|per_item|per_item|per_item|A|official_read|https://www.loc.gov/legal/|20 req/min, 1h block; use /film-and-videos/?fo=json because robots disallows /search
openbeelden|T1|active|history_archive|www.openbeelden.nl|per_item|per_item|per_item|per_item|per_item|per_item|A|official_read|https://www.openbeelden.nl/api|all items CC or PD; robots crawl-delay 10; OAI unreachable once then Identify ok 2026-11-24
commons|T1|active|general,nature,history_archive|commons.wikimedia.org,upload.wikimedia.org|per_item|per_item|per_item|per_item|per_item|per_item|A|official_read|https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia|serial requests per API:Etiquette; documented API allowed
netflix_open|T1|active|cinematic_test|s3.amazonaws.com,opencontent.netflix.com|site_license|CC-BY-4.0|yes|yes|yes|unknown|A|official_read|https://opencontent.netflix.com/|path-restricted to bucket download.opencontent.netflix.com
peertube|T1|active|general|sepiasearch.org|per_item|per_item|per_item|per_item|per_item|per_item|C|probed|https://framasoft.org/en/legals/|instance hosts are resolved at fetch time and validated against the item URL
mixkit|T3|active|general,motion_background|mixkit.co,assets.mixkit.co|per_item|Mixkit-Stock-Video-Free|no|yes|yes|unknown|A|official_read|https://mixkit.co/terms/|link hand-off only, no automated access: terms s.9 forbid access in any way not expressly permitted and bots for mass download
coverr|T3|active|general|coverr.co,cdn.coverr.co|site_license|Coverr|no|yes|yes|no_training|A|official_read|https://coverr.co/license|link hand-off only: website terms 3(vii) forbid robots and any automated access; API/MCP needs an account; skip Premium; AI items flagged
dareful|T2|active|nature,general|dareful.com|site_license|CC-BY-4.0|yes|yes|yes|unknown|B|official_read|https://dareful.com/|licence read from site footer; linked to CC BY 4.0; search and link only (files are streamed via Mux, no direct file)
vidsplay|T2|active|general|www.vidsplay.com|site_license|Vidsplay|yes|yes|yes|no_training|B|official_read|https://www.vidsplay.com/terms/|visible credit link; no as-is redistribution; robots Content-Signal ai-train=no
isorepublic|T2|active|general|isorepublic.com|site_license|CC0-1.0|no|yes|yes|unknown|B|official_read|https://isorepublic.com/license/|
freenaturestock|T2|active|nature|freenaturestock.com|site_license|CC0-1.0|no|yes|yes|unknown|B|official_read|https://freenaturestock.com/license/|robots Content-Signal ai-train=no
beeple|T2|hold|motion_background|www.beeple-crap.com,beeple-crap.com|site_license|CC-unspecified|unknown|yes|yes|unknown|B|official_read|https://www.beeple-crap.com/vjloops|CC version not stated
cutestock|T2|hold|general|cutestockfootage.com|site_license|unknown|unknown|unknown|unknown|unknown|B|probed||
freestockvideo|T2|hold|general|free-stock.video|site_license|unknown|unknown|unknown|unknown|unknown|B|probed||
beachfront|T2|hold|general|www.beachfrontbroll.com|per_item|unknown|unknown|unknown|unknown|unknown|B|probed||
nasa_eol|T2|active|space_science,earth_science|eol.jsc.nasa.gov|public_domain_agency|NASA-media|yes|yes|yes|unknown|A|official_read|https://eol.jsc.nasa.gov/FAQ/|credit Earth Science and Remote Sensing Unit, NASA JSC
esawebb|T2|active|space_science|esawebb.org,cdn.esawebb.org|site_license|CC-BY-4.0|yes|yes|yes|unknown|A|official_read|https://esawebb.org/copyright/|credit not hidden; music excluded
esahubble|T2|active|space_science|esahubble.org,cdn.esahubble.org|site_license|CC-BY-4.0|yes|yes|yes|unknown|A|official_read|https://esahubble.org/copyright/|credit burned in or visible as end credit; music excluded
eso|T2|active|space_science|www.eso.org,cdn.eso.org,cdn2.eso.org|site_license|CC-BY-4.0|yes|yes|yes|disclose_ai_modification|A|official_read|https://www.eso.org/public/outreach/copyright/|must state AI modification
noirlab|T2|active|space_science|noirlab.edu,storage.noirlab.edu|site_license|CC-BY-4.0|yes|yes|yes|unknown|A|official_read|https://noirlab.edu/public/copyright/|
esa|T2|hold|space_science|www.esa.int|per_item|ESA-website-terms|yes|no|no|unknown|A|official_read|https://www.esa.int/terms-and-conditions|site terms non-commercial/no derivatives; separate image-video terms page not found
noaa|T2|hold|earth_science|www.noaa.gov|public_domain_agency|unknown|unknown|unknown|unknown|unknown|A|probed||official page returned 403
usgs|T2|active|earth_science,nature|www.usgs.gov,usgs-ocapsv2-public-input-media.s3.us-west-2.amazonaws.com,usgs-ocapsv2-public-output-media.s3.us-west-2.amazonaws.com,d9-wret.s3.us-west-2.amazonaws.com|public_domain_agency|PD-unless-noted|yes|yes|yes|unknown|A|official_read|https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits|
usfws|T2|hold|wildlife|www.fws.gov|public_domain_agency|unknown|unknown|unknown|unknown|unknown|A|probed||fetched policy index has no licence text
nps|T2|active|nature,wildlife|www.nps.gov|public_domain_agency|PD-unless-noted|yes|yes|yes|unknown|A|official_read|https://www.nps.gov/aboutus/disclaimer.htm|passes only when the item itself says Public domain and credits NPS; NPS-credited without that statement warns; other credits hold
footagearchive|T2|hold|history_archive|www.freestockfootagearchive.com|per_item|unknown|unknown|unknown|unknown|unknown|B|probed||
pdmovie|T2|hold|history_archive|publicdomainmovie.net|per_item|unknown|unknown|unknown|unknown|unknown|B|probed||
footagefarm|T2|hold|history_archive|www.footagefarm.com|per_item|unknown|unknown|unknown|unknown|unknown|B|probed||
eu_av|T2|active|government|audiovisual.ec.europa.eu|per_item|CC-BY-4.0|yes|yes|yes|unknown|A|official_read|https://audiovisual.ec.europa.eu/en/conditions-of-use|no EU-purpose limit found; check each file; do not distort meaning; music and persons excluded
whitehouse|T2|hold|government|www.whitehouse.gov|public_domain_agency|unknown|unknown|unknown|unknown|unknown|A|probed||
blender_studio|T2|active|animation|studio.blender.org|site_license|CC-BY-4.0|yes|yes|yes|unknown|A|official_read|https://studio.blender.org/terms-and-conditions/|unless notified otherwise; robots Content-Signal ai-train=no; provenance=animation
cinestudy|T2|hold|cinematic_test|cinestudy.org|per_item|unknown|unknown|unknown|unknown|unknown|B|probed||
tcmb|T2|hold|chinese_asia|memory.culture.tw,tcmb.culture.tw|per_item|per_item|per_item|per_item|per_item|per_item|A|probed|https://tcmb.culture.tw/zh-tw/FAQ/170|official page timed out
pexels|T3|active|general|www.pexels.com,videos.pexels.com|site_license|unknown|unknown|unknown|unknown|unknown|A|probed|https://www.pexels.com/license/|403; user reads terms in browser
pixabay|T3|active|general|pixabay.com,cdn.pixabay.com|site_license|unknown|unknown|unknown|unknown|unknown|A|probed|https://pixabay.com/service/license-summary/|403
videezy|T3|active|general|www.videezy.com|per_item|unknown|unknown|unknown|unknown|unknown|B|probed|https://www.videezy.com/licensing|403
nasa_jpl|T3|active|space_science|www.jpl.nasa.gov|public_domain_agency|unknown|unknown|unknown|unknown|unknown|A|probed||403
britishcouncil|T3|active|history_archive|film.britishcouncil.org|per_item|unknown|unknown|unknown|unknown|unknown|A|probed||403
pond5_pd|T3|active|history_archive|www.pond5.com|per_item|unknown|unknown|unknown|unknown|unknown|B|probed||
ep_multimedia|T3|active|government|multimedia.europarl.europa.eu|per_item|unknown|unknown|unknown|unknown|unknown|A|probed||403; purpose limit reported by search summary only; R9 applies until read
nih|T3|active|life_science|www.nih.gov|public_domain_agency|unknown|unknown|unknown|unknown|unknown|A|probed||
fema|T3|active|government|www.fema.gov|public_domain_agency|unknown|unknown|unknown|unknown|unknown|A|probed||
dvids|T3|active|government|www.dvidshub.net|public_domain_agency|unknown|unknown|unknown|unknown|unknown|A|probed||
vimeo_cc|T3|active|general|vimeo.com|per_item|per_item|per_item|per_item|per_item|per_item|C|probed||
tfai|T3|active|chinese_asia|www.tfai.org.tw|per_item|unknown|unknown|unknown|unknown|unknown|A|probed||403
nara|T3|active|history_archive|catalog.archives.gov|per_item|unknown|unknown|unknown|unknown|unknown|A|probed||moved from T2: robots is Disallow / for all agents
flickr_cc|T3|active|general|www.flickr.com|per_item|per_item|per_item|per_item|per_item|per_item|C|official_read|https://www.flickr.com/creativecommons/|moved from T2: robots is Disallow / for generic agents
usda_flickr|T3|active|government|www.flickr.com|per_item|per_item|per_item|per_item|per_item|per_item|A|probed||moved from T2 with flickr_cc
gongu|T3|active|chinese_asia|gongu.copyright.or.kr,www.kogl.or.kr|per_item|KOGL|per_item|per_item|per_item|unknown|A|official_read|https://www.kogl.or.kr/info/license.do|moved from T2: robots disallows download endpoints; KOGL types 0-4 and AI; AI-type conditions not resolved
cil|T4|active|life_science|www.cellimagelibrary.org|per_item|per_item|per_item|per_item|per_item|per_item|A|official_read|https://www.cellimagelibrary.org/pages/license|moved from T2: robots has conflicting * groups, one Disallow /
xiph|T4|active|cinematic_test|media.xiph.org|per_item|per_item|per_item|per_item|per_item|per_item|B|official_read|https://media.xiph.org/video/derf/|moved from T2: robots disallows media files
schmidt|T4|active|ocean|schmidtocean.org|per_item|CC-BY-NC-SA-4.0|yes|no|yes|unknown|A|official_read|https://schmidtocean.org/footage-requests-and-consent/|request form; lobbying use forbidden per search summary
actionvfx|T4|active|vfx|www.actionvfx.com|site_license|unknown|unknown|unknown|unknown|unknown|B|probed||
smithsonian|T4|active|history_archive|www.si.edu|per_item|unknown|unknown|unknown|unknown|unknown|A|probed||
europeana|T4|active|history_archive|www.europeana.eu|per_item|per_item|per_item|per_item|per_item|per_item|A|probed||
dpla|T4|active|history_archive|dp.la|per_item|per_item|per_item|per_item|per_item|per_item|A|probed||
trove|T4|active|history_archive|trove.nla.gov.au|per_item|per_item|per_item|per_item|per_item|per_item|A|probed||
digitalnz|T4|active|history_archive|digitalnz.org|per_item|per_item|per_item|per_item|per_item|per_item|A|probed||
youtube_cc|T4|active|general|www.youtube.com|per_item|per_item|per_item|per_item|per_item|per_item|C|probed||
aigei|T4|active|chinese_asia|www.aigei.com|per_item|per_item|per_item|per_item|per_item|per_item|C|probed||
vjshi|T4|active|chinese_asia|www.vjshi.com|per_item|unknown|unknown|unknown|unknown|unknown|C|probed||
magnific|X|blocked|general||site_license|unknown|unknown|unknown|unknown|unknown|C|user_supplied||official licence page not read by this project; excluded until it is
vecteezy|X|blocked|general||site_license|unknown|unknown|unknown|unknown|unknown|C|user_supplied||official licence page not read by this project; excluded until it is
productioncrate|X|blocked|vfx||site_license|unknown|unknown|unknown|unknown|unknown|C|user_supplied||official licence page not read by this project; excluded until it is
motionplaces|X|blocked|general||site_license|unknown|unknown|unknown|unknown|unknown|C|user_supplied||official licence page not read by this project; excluded until it is
chaodian|X|blocked|chinese_asia||site_license|unknown|unknown|unknown|unknown|unknown|C|user_supplied||official licence page not read by this project; excluded until it is
jaxa|X|excluded|space_science|jda.jaxa.jp|site_license|JAXA|yes|no|no|unknown|A|official_read|https://global.jaxa.jp/policy.html|no modification, no commercial without permission; Digital Archives own copyright page not readable
eumetsat|X|excluded|earth_science|www.eumetsat.int|site_license|EUMETSAT-website|yes|no|unknown|unknown|A|official_read|https://www.eumetsat.int/about-us/terms-use|website content personal non-commercial; Data Policy covers data not media
nautilus|X|excluded|ocean|nautiluslive.org|per_item|all-rights-reserved|unknown|unknown|unknown|unknown|A|official_read|https://nautiluslive.org/pressroom|licensed on request only
un_av|X|excluded|government|media.un.org|site_license|UN-licence-agreement|yes|unknown|no|unknown|A|official_read|https://media.un.org/avlibrary/en/guidelines|signed agreement and fees; files cannot be altered
'''
out=[]
for l in R.strip().splitlines():
    f=l.split('|'); assert len(f)==15,(len(f),l)
    i,t,st,tp,h,lm,lid,at,co,de,ai,tr,v,u,n=f
    t1rate={'loc':(1,5000),'openbeelden':(1,10000),'commons':(1,1000)}.get(i,(2,1000))
    r=dict(id=i,tier=None if t=='X' else t,status=st,topics=tp.split(','),hosts=[x for x in h.split(',') if x],redirect_host_suffixes=['.us.archive.org','.ca.archive.org'] if i in('ia','ia_nasa') else [],license_model=lm,license_id=lid,
      attribution_required=at,commercial=co,derivatives=de,ai_use=ai,source_trust=tr,
      gate_default='block' if st in('blocked','excluded') else 'per_rules' if (v=='official_read' and st in('active','degraded') and 'unspecified' not in lid) else 'hold',
      verify_status=v,verified_at='2026-11-23' if i=='ia' else D if v=='official_read' and i!='nasa_svs' else '2026-11-20',
      politeness=dict(max_concurrency=t1rate[0],min_interval_ms=t1rate[1],ua_required=True),notes=n)
    if u: r['terms_url']=u
    out.append(r)
p=pathlib.Path(__file__).resolve().parents[1]/'data/sources.yaml'
tmp=p.with_suffix('.tmp'); tmp.write_text(yaml.safe_dump({'schema_version':'1.0.0','generated_at':D,'sources':out},allow_unicode=True,sort_keys=False)); tmp.replace(p)
