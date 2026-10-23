$ErrorActionPreference = 'Stop'

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root
$source = 'C:\Users\amg30\AppData\Local\Packages\Microsoft.ScreenSketch_8wekyb3d8bbwe\TempState\Recordings\20261023-0030-17.2178809.mp4'
$ffmpeg = Join-Path $root 'data\walkthrough-tools\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe'
$deliverables = Join-Path $root 'deliverables'
$work = Join-Path $root 'data\walkthrough-edit-work'
$finalVideo = Join-Path $deliverables 'impactcircles_walkthrough.mp4'
$assPath = Join-Path $deliverables 'impactcircles_walkthrough_captions.ass'
$srtPath = Join-Path $deliverables 'impactcircles_walkthrough_captions.srt'
$scriptPath = Join-Path $deliverables 'impactcircles_walkthrough_voiceover_script.txt'
$wavPath = Join-Path $deliverables 'impactcircles_walkthrough_voiceover.wav'
$manifestPath = Join-Path $work 'scenes.json'
$weekTwoPostFrame = Join-Path $work 'week-two-linkedin-post.png'

foreach ($path in @($source, $ffmpeg)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required file not found: $path" }
}
New-Item -ItemType Directory -Force -Path $deliverables, $work | Out-Null

# The public Week 2 LinkedIn post is visible only briefly before the recording
# switches screens, so capture a clean frame and hold it for the narration.
& $ffmpeg -hide_banner -loglevel error -y -ss 357.0 -i $source -frames:v 1 -update 1 $weekTwoPostFrame
if ($LASTEXITCODE -ne 0) { throw "Could not capture the Week 2 LinkedIn post frame." }

function Get-WavDuration([string]$path) {
    $reader = [System.IO.BinaryReader]::new([System.IO.File]::OpenRead($path))
    try {
        $byteRate = 0
        $dataSize = 0
        $reader.BaseStream.Position = 12
        while ($reader.BaseStream.Position + 8 -le $reader.BaseStream.Length) {
            $chunk = [System.Text.Encoding]::ASCII.GetString($reader.ReadBytes(4))
            $chunkSize = $reader.ReadInt32()
            $payloadStart = $reader.BaseStream.Position
            if ($chunk -eq 'fmt ') {
                $reader.BaseStream.Position = $payloadStart + 8
                $byteRate = $reader.ReadInt32()
            }
            if ($chunk -eq 'data') {
                $dataSize = $chunkSize
                break
            }
            $reader.BaseStream.Position = $payloadStart + $chunkSize + ($chunkSize % 2)
        }
        if ($byteRate -le 0 -or $dataSize -le 0) { throw "Unsupported or empty WAV file: $path" }
        return $dataSize / [double]$byteRate
    } finally { $reader.Dispose() }
}

# Short excerpts retain the complete two-week story while removing login, scrolling,
# file-picker detours, and wait time. Seconds are measured from the original recording.
$scenes = @(
    @{ Start = 10.0; End = 18.0; En = 'We follow one project from research and review to publication, then show how week two builds on week one.'; Ar = 'نتابع مشروعًا من البحث والمراجعة إلى النشر، ثم نرى كيف يبني الأسبوع الثاني على الأسبوع الأول.' },
    @{ Start = 38.0; End = 47.0; En = 'The agent combines supplied context with linked evidence, so reviewers can check the sources behind each draft.'; Ar = 'يجمع الوكيل السياق المقدم مع الأدلة المرتبطة، ليتمكن المراجعون من التحقق من مصادر كل مسودة.' },
    @{ Start = 74.0; End = 81.0; En = 'It prepares channel-ready drafts for LinkedIn, the newsletter, and the future website.'; Ar = 'يُعد مسودات مناسبة للنشر على لينكدإن والنشرة البريدية والموقع الإلكتروني مستقبلًا.' },
    @{ Start = 125.0; End = 140.0; En = 'For Arid Sun week one, I select the project, set its reporting dates, and add source notes. The agent generates channel drafts for review.'; Ar = 'في الأسبوع الأول من مشروع «الشمس القاحلة»، أختار المشروع وأحدد فترة التقرير وأضيف ملاحظات المصادر. ثم يُنشئ الوكيل مسودات القنوات للمراجعة.' },
    @{ Start = 151.0; End = 163.0; En = 'A human reviews the copy and citations, can make edits, and approves the exact revision before anything is queued for delivery.'; Ar = 'يراجع شخصٌ النص والاستشهادات، ويمكنه تعديلها، ثم يوافق على النسخة المحددة قبل إدراجها في قائمة الإرسال.' },
    @{ Start = 178.0; End = 192.0; En = 'For this demo, I manually pressed Run once instead of waiting for the fifteen-minute schedule. LinkedIn publishes after approval; Gmail gets a review draft, never an auto-sent email.'; Ar = 'في هذا العرض، شغّلت السيناريو يدويًا عبر «Run once» بدل انتظار الجدولة كل 15 دقيقة. يُنشر محتوى لينكدإن بعد الموافقة، وتُحفظ رسالة Gmail كمسودة للمراجعة ولا تُرسل تلقائيًا.' },
    @{ Start = 202.0; End = 211.0; En = 'The first-week update is live on LinkedIn, with its own public post link.'; Ar = 'أصبح تحديث الأسبوع الأول منشورًا على لينكدإن، وله رابط عام خاص به.' },
    @{ Start = 258.0; End = 268.0; En = 'For week two, I use the same project with a new reporting window and fresh notes.'; Ar = 'في الأسبوع الثاني، أستخدم المشروع نفسه مع فترة تقرير جديدة وملاحظات محدّثة.' },
    @{ Start = 278.0; End = 293.0; En = 'The agent checks prior published work. The week-one post appears in the week-two context, helping the new update continue the story rather than repeat it.'; Ar = 'يراجع الوكيل المنشورات السابقة. يظهر منشور الأسبوع الأول ضمن سياق الأسبوع الثاني، ليساعد التحديث الجديد على مواصلة القصة بدل تكرارها.' },
    @{ Start = 302.0; End = 308.0; En = 'I manually run the scenario again for this test.'; Ar = 'أشغّل السيناريو يدويًا مرة أخرى لهذا الاختبار.' },
    @{ Start = 335.0; End = 348.0; En = 'The activity confirms LinkedIn delivery, while the newsletter stays an unsent Gmail draft. The app keeps the delivery history. Website publishing waits for a CMS connection; its Make route is disabled.'; Ar = 'يؤكد سجل النشاط النشر على لينكدإن، بينما تبقى النشرة مسودة Gmail غير مُرسلة. يحتفظ التطبيق بسجل التسليم. وينتظر نشر الموقع ربط نظام إدارة محتوى؛ فمساره في Make معطّل حاليًا.' },
    @{ Start = 358.0; End = 358.5; Hold = 5.5; Still = $true; En = 'Here is the published week-two LinkedIn update.'; Ar = 'وهذا تحديث الأسبوع الثاني المنشور على لينكدإن.' },
    @{ Start = 369.0; End = 373.3; En = 'Both weeks remain together in the content library.'; Ar = 'يبقى محتوى الأسبوعين معًا في مكتبة المحتوى.' }
)

$utf8 = [System.Text.UTF8Encoding]::new($false)
$narrationLines = [System.Collections.Generic.List[string]]::new()
$manifestScenes = [System.Collections.Generic.List[object]]::new()
$captionEvents = [System.Collections.Generic.List[object]]::new()
$videoFilters = [System.Collections.Generic.List[string]]::new()
$audioFilters = [System.Collections.Generic.List[string]]::new()
$videoInputs = [System.Collections.Generic.List[string]]::new()
$audioInputs = [System.Collections.Generic.List[string]]::new()
$subtitleOffset = 0.0
$manifestScenes = for ($j = 0; $j -lt $scenes.Count; $j++) {
    [pscustomobject]@{ Index = $j + 1; Start = $scenes[$j].Start; End = $scenes[$j].End; Hold = $scenes[$j].Hold; English = $scenes[$j].En; Arabic = $scenes[$j].Ar }
}
[System.IO.File]::WriteAllText($manifestPath, (ConvertTo-Json -InputObject @($manifestScenes) -Depth 4), $utf8)

for ($i = 0; $i -lt $scenes.Count; $i++) {
    $scene = $scenes[$i]
    $hold = if ($scene.Hold) { [double]$scene.Hold } else { 0.0 }
    $slot = [double]$scene.End - [double]$scene.Start + $hold
    $wav = Join-Path $work ('voice-{0:D2}-fixed.wav' -f ($i + 1))
    if (-not (Test-Path -LiteralPath $wav -PathType Leaf)) {
        throw "Narration audio is missing: $wav. Run 'uv run python -m scripts.generate_walkthrough_voiceover' from the repository root first."
    }
    $voiceDuration = Get-WavDuration $wav
    $tempo = [Math]::Max(1.0, $voiceDuration / ($slot - 0.4))
    if ($tempo -gt 1.25) { throw ("Narration scene {0} is too long ({1:N1}s for {2:N1}s). Shorten the narration before rendering." -f ($i + 1), $voiceDuration, $slot) }

    $sceneNo = $i.ToString('D2')
    $holdFilter = if ($hold -gt 0) { ",tpad=stop_mode=clone:stop_duration=$hold" } else { '' }
    if ($scene.Still) {
        $stillInput = $scenes.Count + 1
        $videoFilters.Add("[$stillInput`:v]trim=duration=$slot,setpts=PTS-STARTPTS,fps=30[v$sceneNo]")
    } else {
        $videoFilters.Add("[0:v]trim=start=$($scene.Start):end=$($scene.End),setpts=PTS-STARTPTS$holdFilter,fps=30[v$sceneNo]")
    }
    $videoInputs.Add("[v$sceneNo]")
    $inputIndex = $i + 1
    $audioFilters.Add("[$inputIndex`:a]aresample=48000,atempo=$tempo,apad=pad_dur=$slot,atrim=duration=$slot,asetpts=PTS-STARTPTS[a$sceneNo]")
    $audioInputs.Add("[a$sceneNo]")

    $captionStart = $subtitleOffset + 0.08
    $captionEnd = [Math]::Min($subtitleOffset + $slot - 0.05, $captionStart + ($voiceDuration / $tempo) + 0.65)
    $captionEvents.Add([pscustomobject]@{ Start = $captionStart; End = $captionEnd; En = $scene.En; Ar = $scene.Ar })
    $narrationLines.Add(("{0:D2}. {1}" -f ($i + 1), $scene.En))
    $subtitleOffset += $slot
}

$totalDuration = $subtitleOffset
if ($totalDuration -gt 150.0) { throw "Edit would be longer than 2 minutes 30 seconds ($totalDuration seconds)." }

function ConvertTo-AssTime([double]$seconds) {
    $cs = [int][Math]::Floor(($seconds - [Math]::Floor($seconds)) * 100)
    $whole = [int][Math]::Floor($seconds)
    $hours = [int][Math]::Floor($whole / 3600)
    $minutes = [int][Math]::Floor(($whole % 3600) / 60)
    $secs = $whole % 60
    return ('{0}:{1:D2}:{2:D2}.{3:D2}' -f $hours, $minutes, $secs, $cs)
}

$ass = [System.Collections.Generic.List[string]]::new()
$ass.Add('[Script Info]')
$ass.Add('ScriptType: v4.00+')
$ass.Add('PlayResX: 1920')
$ass.Add('PlayResY: 1080')
$ass.Add('WrapStyle: 0')
$ass.Add('ScaledBorderAndShadow: yes')
$ass.Add('')
$ass.Add('[V4+ Styles]')
$ass.Add('Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding')
$ass.Add('Style: Bilingual,Arial,34,&H00FFFFFF,&H000000FF,&H00101812,&HAA102018,0,0,0,0,100,100,0,0,3,1.5,0,2,100,100,70,1')
$ass.Add('')
$ass.Add('[Events]')
$ass.Add('Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text')
$srt = [System.Collections.Generic.List[string]]::new()
for ($i = 0; $i -lt $captionEvents.Count; $i++) {
    $event = $captionEvents[$i]
    $start = ConvertTo-AssTime $event.Start
    $end = ConvertTo-AssTime $event.End
    $safeEn = $event.En.Replace('{', '').Replace('}', '')
    $safeAr = $event.Ar.Replace('{', '').Replace('}', '')
    $ass.Add("Dialogue: 0,$start,$end,Bilingual,,0,0,0,,{\an2}$safeEn\N{\rBilingual\fnArial\fs33\fe178}$safeAr")

    $srtStart = [TimeSpan]::FromSeconds($event.Start).ToString('hh\:mm\:ss\,fff')
    $srtEnd = [TimeSpan]::FromSeconds($event.End).ToString('hh\:mm\:ss\,fff')
    $srt.Add([string]($i + 1))
    $srt.Add("$srtStart --> $srtEnd")
    $srt.Add($event.En)
    $srt.Add($event.Ar)
    $srt.Add('')
}
[System.IO.File]::WriteAllLines($assPath, $ass, $utf8)
[System.IO.File]::WriteAllLines($srtPath, $srt, $utf8)
[System.IO.File]::WriteAllLines($scriptPath, $narrationLines, $utf8)

$ffArgs = [System.Collections.Generic.List[string]]::new()
$ffArgs.AddRange([string[]]@('-hide_banner','-y','-i',$source))
for ($i = 0; $i -lt $scenes.Count; $i++) { $ffArgs.Add('-i'); $ffArgs.Add((Join-Path $work ('voice-{0:D2}-fixed.wav' -f ($i + 1)))) }
$ffArgs.AddRange([string[]]@('-loop','1','-framerate','30','-t','6','-i',$weekTwoPostFrame))

$filterParts = [System.Collections.Generic.List[string]]::new()
$filterParts.AddRange([string[]]$videoFilters)
$filterParts.AddRange([string[]]$audioFilters)
$videoConcat = $videoInputs -join ''
$audioConcat = $audioInputs -join ''
$filterParts.Add("${videoConcat}concat=n=$($scenes.Count):v=1:a=0,scale=1920:1024,pad=1920:1080:0:28:color=black,drawbox=x=0:y=28:w=1920:h=137:color=0x12372D@0.96:t=fill,drawtext=fontfile='C\:/Windows/Fonts/arialbd.ttf':text='IMPACTCIRCLES  |  CONTENT AGENT WALKTHROUGH':fontcolor=white:fontsize=34:x=76:y=70,ass=filename=deliverables/impactcircles_walkthrough_captions.ass[vout]")
$filterParts.Add("${audioConcat}concat=n=$($scenes.Count):v=0:a=1,afade=t=out:st=$([Math]::Max(0, $totalDuration - 1.2)):d=1.2,loudnorm=I=-16:TP=-1.5:LRA=11[aout]")
$filter = $filterParts -join ';'
$ffArgs.AddRange([string[]]@('-filter_complex',$filter,'-map','[vout]','-map','[aout]','-c:v','libx264','-preset','medium','-crf','21','-pix_fmt','yuv420p','-c:a','aac','-b:a','160k','-ar','48000','-movflags','+faststart',$finalVideo))

Write-Host ("Rendering {0} selected excerpts ({1:N1}s), with {2} English/Arabic caption cards..." -f $scenes.Count, $totalDuration, $captionEvents.Count)
& $ffmpeg @ffArgs
if ($LASTEXITCODE -ne 0) { throw "FFmpeg failed with exit code $LASTEXITCODE" }

& $ffmpeg -hide_banner -y -i $finalVideo -map 0:a:0 -c:a pcm_s16le -ar 48000 -ac 2 $wavPath
if ($LASTEXITCODE -ne 0) { throw "Voiceover WAV export failed with exit code $LASTEXITCODE" }

Write-Host "Finished: $finalVideo"
Write-Host "Captions: $srtPath (English above Arabic)"
Write-Host "Narration script: $scriptPath"
Write-Host "Voiceover: $wavPath"
Write-Host "Duration: $([TimeSpan]::FromSeconds($totalDuration).ToString('mm\:ss'))"
