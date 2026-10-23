param([int]$Port = 8001, [string]$PublicUrl = '')
$ErrorActionPreference = 'Stop'
if (-not (Get-Command ngrok -ErrorAction SilentlyContinue)) {
    throw 'Install the ngrok agent and authenticate it with your ngrok account first.'
}
if ($PublicUrl) {
    $taskUri = [Uri]$PublicUrl
    if ($taskUri.Scheme -ne 'https' -or $taskUri.AbsolutePath -ne '/' `
        -or $taskUri.UserInfo -or $taskUri.Query -or $taskUri.Fragment) {
        throw 'PublicUrl must be your assigned HTTPS ngrok origin, without a path.'
    }
    & ngrok http $Port --url $PublicUrl
} else {
    # The first run discovers the assigned URL; paste it into .env.make.
    & ngrok http $Port
}
