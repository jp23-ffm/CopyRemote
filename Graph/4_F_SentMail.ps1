Function F_SentMail {
    param(
        [Parameter(Mandatory = $true)] [string]$S_MailOfService,
        [Parameter(Mandatory = $false)] [string]$S_LoginExchange,
        [Parameter(Mandatory = $false)] [string]$S_Domain,
        [Parameter(Mandatory = $false)] [string]$S_PasswordExchange,
        [Parameter(Mandatory = $true)] [string]$S_Connectionstring,
        [Parameter(Mandatory = $true)] [string]$S_Body,
        [Parameter(Mandatory = $true)] [string]$S_SubjectMail,
        [Parameter(Mandatory = $true)] [array]$A_ToRecipients
    )
    
    Try {
        # === CHANGEMENT : Initialisation Graph au lieu de EWS ===
        $connectionResult = Initialize-EwsCompatConnection -UserEmail $S_MailOfService
        
        if (-not $connectionResult.Success) {
            Write-Error "Erreur lors de l'initialisation de la connexion Graph"
            Return @(1, $connectionResult.Error)
        }
        
        Write-Verbose "Connexion Graph initialisée pour: $S_MailOfService"
        
        # === CHANGEMENT : Envoi via Graph au lieu de EWS ===
        # Conversion du tableau de destinataires (si nécessaire)
        $toRecipients = @()
        foreach ($recipient in $A_ToRecipients) {
            # Si c'est déjà une string, on l'ajoute directement
            if ($recipient -is [string]) {
                $toRecipients += $recipient
            }
            # Si c'est un objet avec une propriété Address ou EmailAddress
            elseif ($recipient.Address) {
                $toRecipients += $recipient.Address
            }
            elseif ($recipient.EmailAddress) {
                $toRecipients += $recipient.EmailAddress
            }
        }
        
        # Envoi du message
        $result = Send-EwsCompatMessage -Subject $S_SubjectMail `
                                        -Body $S_Body `
                                        -BodyType "HTML" `
                                        -ToRecipients $toRecipients `
                                        -SaveToSentItems $true
        
        if ($result.Success) {
            Write-Verbose "Email envoyé avec succès"
            Return @(0, $null)
        }
        else {
            Write-Error "Échec de l'envoi: $($result.Error)"
            Return @(1, $result.Error)
        }
    }
    Catch {
        Write-Error "Erreur dans F_SentMail: $_"
        Return @(1, $_.Exception.Message)
    }
}