#!/usr/bin/perl
# Şirket Exchange gelen kutusunu EWS (Exchange Web Services) ile SADECE OKUR:
# yalnızca FindItem çağrısı yapılır, hiçbir mail okundu işaretlenmez, silinmez, taşınmaz.
# Son N saatteki mailleri düz metin olarak yazdırır.
# Ayarlar: aynı klasördeki mail.conf. Şifre: macOS Anahtar Zinciri (Keychain).
use utf8;
use strict;
use warnings;
use Encode qw(decode);
use POSIX qw(strftime);
use Time::Local qw(timegm);
use File::Basename qw(dirname);
use File::Temp qw(tempfile);
use IPC::Open2 qw(open2);
use Cwd qw(abs_path);

binmode STDOUT, ':encoding(UTF-8)';
binmode STDERR, ':encoding(UTF-8)';
# İsteğe bağlı: çıktı dosyası (ör. fetch_mail.pl raporlar/.son_cekim.txt)
# --ajanda: sadece "Ajanda:" konulu komut maillerini yazdırır (saatlik ajanda senkronu için).
my $ajanda_only = (@ARGV && $ARGV[0] eq "--ajanda") ? shift(@ARGV) : 0;
# --saat N: son N saate bak (gün içi ara kontroller için).
my $hours_arg = (@ARGV >= 2 && $ARGV[0] eq "--saat" && $ARGV[1] =~ /^\d+$/) ? (shift(@ARGV), shift(@ARGV))[1] : undef;
if (@ARGV) { open STDOUT, '>:encoding(UTF-8)', $ARGV[0] or die "Çıktı dosyası açılamadı: $ARGV[0]\n" }

my %c = (hours => 24, max => 2000, name => q{});
my $dir  = dirname(abs_path($0));
my $conf = "$dir/mail.conf";
open my $cf, '<:encoding(UTF-8)', $conf or die "Ayar dosyası açılamadı: $conf\n";
while (<$cf>) {
    next if /^\s*(#|$)/;
    $c{$1} = $2 if /^\s*(\w+)\s*=\s*(.*?)\s*$/;
}
close $cf;
$c{hours} = $hours_arg if defined $hours_arg;
$c{hours} = 48 if $ajanda_only && !$ENV{MAIL_HOURS};
$c{hours} = $ENV{MAIL_HOURS} if ($ENV{MAIL_HOURS} // '') =~ /^\d+$/;    # tek seferlik geriye bakış (saat)
for (qw(host user keychain_service)) {
    die "mail.conf içinde '$_' eksik\n" unless $c{$_} && $c{$_} !~ /BURAYA/;
}

open my $ph, '-|', '/usr/bin/security', 'find-generic-password',
    '-s', $c{keychain_service}, '-a', $c{user}, '-w'
    or die "Keychain okunamadı\n";
my $pass = <$ph>;
close $ph;
die "Keychain'de şifre bulunamadı (servis: $c{keychain_service}, hesap: $c{user})\n"
    unless defined $pass && length $pass;
chomp $pass;

my $cutoff = time - $c{hours} * 3600;
my $since  = strftime('%Y-%m-%dT%H:%M:%SZ', gmtime($cutoff));

my $soap = <<"XML";
<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
  xmlns:t="http://schemas.microsoft.com/exchange/services/2006/types"
  xmlns:m="http://schemas.microsoft.com/exchange/services/2006/messages">
 <soap:Header><t:RequestServerVersion Version="Exchange2016"/></soap:Header>
 <soap:Body>
  <m:FindItem Traversal="Shallow">
   <m:ItemShape>
    <t:BaseShape>IdOnly</t:BaseShape>
    <t:AdditionalProperties>
     <t:FieldURI FieldURI="item:Subject"/>
     <t:FieldURI FieldURI="message:From"/>
     <t:FieldURI FieldURI="item:DisplayTo"/>
     <t:FieldURI FieldURI="item:DisplayCc"/>
     <t:FieldURI FieldURI="item:DateTimeReceived"/>
     <t:FieldURI FieldURI="message:IsRead"/>
     <t:FieldURI FieldURI="item:Importance"/>
     <t:FieldURI FieldURI="item:HasAttachments"/>
     <t:FieldURI FieldURI="item:Preview"/>
    </t:AdditionalProperties>
   </m:ItemShape>
   <m:IndexedPageItemView MaxEntriesReturned="__PAGE__" Offset="__OFFSET__" BasePoint="Beginning"/>
   <m:Restriction>
    <t:IsGreaterThanOrEqualTo>
     <t:FieldURI FieldURI="item:DateTimeReceived"/>
     <t:FieldURIOrConstant><t:Constant Value="$since"/></t:FieldURIOrConstant>
    </t:IsGreaterThanOrEqualTo>
   </m:Restriction>
   <m:SortOrder>
    <t:FieldOrder Order="Descending"><t:FieldURI FieldURI="item:DateTimeReceived"/></t:FieldOrder>
   </m:SortOrder>
   <m:ParentFolderIds><t:DistinguishedFolderId Id="inbox"/></m:ParentFolderIds>
  </m:FindItem>
 </soap:Body>
</soap:Envelope>
XML

# Kimlik bilgisi curl'e komut satırından değil stdin'den verilir (ps çıktısında görünmez).
(my $esc = "$c{user}:$pass") =~ s/(["\\])/\\$1/g;
undef $pass;

sub ews_call {
    my ($body) = @_;
    # Geçici ağ/SSL hatalarında 3 kez dener.
    for my $try (1 .. 3) {
        my $r = eval { ews_once($body) };
        return $r if defined $r;
        die $@ if $@ =~ /HTTP 401/ || $try == 3;
        sleep 5 * $try;
    }
}

sub ews_once {
    my ($body) = @_;
    my ($tfh, $tfile) = tempfile(UNLINK => 1);
    binmode $tfh, ':encoding(UTF-8)';
    print $tfh $body;
    close $tfh;
    my $pid = open2(my $out, my $in, '/usr/bin/curl', '-s', '-K', '-', '--ntlm', '--max-time', '120',
        '-H', 'Content-Type: text/xml; charset=utf-8', '--data-binary', "\@$tfile",
        '-w', "\nHTTP_STATUS=%{http_code}", "https://$c{host}/EWS/Exchange.asmx");
    print $in qq{user = "$esc"\n};
    close $in;
    my $resp = do { local $/; <$out> } // '';
    waitpid $pid, 0;
    $resp = decode('UTF-8', $resp);

    my ($http) = $resp =~ /HTTP_STATUS=(\d+)\s*\z/;
    die "Exchange'e bağlanılamadı (curl hata kodu " . ($? >> 8) . ")\n" unless $http && $http ne '000';
    die "Giriş başarısız (HTTP 401): şifre ya da kullanıcı adı hatalı\n" if $http == 401;
    die "Exchange hatası (HTTP $http)\n" unless $http == 200;
    return $resp;
}

sub find_page {
    my ($offset, $page) = @_;
    (my $body = $soap) =~ s/__OFFSET__/$offset/;
    $body =~ s/__PAGE__/$page/;
    my $resp = ews_call($body);
    if ($resp =~ /ResponseClass="Error".*?<m:MessageText>(.*?)<\/m:MessageText>/s) {
        die "Exchange hatası: $1\n";
    }
    return $resp;
}

sub xml_attr { my $v = shift; $v =~ s/&/&amp;/g; $v =~ s/"/&quot;/g; $v =~ s/</&lt;/g; return $v }

# Seçili maillerin gövde metni (GetItem salt okunurdur, maili okundu işaretlemez).
sub fetch_bodies {
    my @ids = @_;
    my %body;
    while (my @chunk = splice @ids, 0, 40) {
        my $idxml = join '', map { '<t:ItemId Id="' . xml_attr($_) . '"/>' } @chunk;
        my $resp = ews_call(<<"XML");
<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
  xmlns:t="http://schemas.microsoft.com/exchange/services/2006/types"
  xmlns:m="http://schemas.microsoft.com/exchange/services/2006/messages">
 <soap:Header><t:RequestServerVersion Version="Exchange2016"/></soap:Header>
 <soap:Body>
  <m:GetItem>
   <m:ItemShape><t:BaseShape>IdOnly</t:BaseShape><t:BodyType>Text</t:BodyType>
    <t:AdditionalProperties><t:FieldURI FieldURI="item:Body"/></t:AdditionalProperties>
   </m:ItemShape>
   <m:ItemIds>$idxml</m:ItemIds>
  </m:GetItem>
 </soap:Body>
</soap:Envelope>
XML
        for my $item ($resp =~ /<t:Message>(.*?)<\/t:Message>/gs) {
            my ($id) = $item =~ /<t:ItemId Id="([^"]+)"/ or next;
            my ($b)  = $item =~ /<t:Body[^>]*>(.*?)<\/t:Body>/s;
            $body{unxml($id)} = unxml($b // '');
        }
    }
    return %body;
}

sub unxml {
    my $v = shift // return '';
    $v =~ s/&lt;/</g; $v =~ s/&gt;/>/g; $v =~ s/&quot;/"/g; $v =~ s/&apos;/'/g;
    $v =~ s/&#x([0-9a-f]+);/chr(hex $1)/gie; $v =~ s/&#(\d+);/chr($1)/ge;
    $v =~ s/&amp;/&/g;
    return $v;
}
sub tag { my ($xml, $name) = @_; $xml =~ /<t:$name>(.*?)<\/t:$name>/s ? unxml($1) : '' }

sub local_time {
    my $d = shift;
    return $d unless $d =~ /^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)Z$/;
    return strftime('%d.%m.%Y %H:%M', localtime(timegm($6, $5, $4, $3, $2 - 1, $1)));
}

# Türkçe büyük/küçük harf ve noktalı/noktasız i farkını yok sayarak karşılaştırma için.
sub norm {
    my $s = lc(shift // '');
    $s =~ tr/ıİçğöşüâî/iicgosuai/;
    $s =~ s/i̇/i/g;
    $s =~ s/[^a-z0-9@.]+/ /g;
    return $s;
}

sub owa_link {
    (my $id = shift) =~ s/([^A-Za-z0-9\-._~])/sprintf('%%%02X', ord $1)/ge;
    return "https://$c{host}/owa/?ItemID=$id&exvsurl=1&viewmodel=ReadMessageItem";
}

# "RE: FW: Ynt: konu" -> "konu" (yazışma zincirlerini gruplamak için)
sub thread_key {
    my $s = shift // '';
    1 while $s =~ s/^\s*(re|fw|fwd|ynt|yanit|yanıt|ilt|ilet|iletildi|aw|wg|tr)\s*:\s*//i;
    return norm($s) =~ s/^\s+|\s+$//gr;
}

my @msgs;
my $total = 0;
for (my $offset = 0; $offset < $c{max}; $offset += 500) {
    my $resp = find_page($offset, 500);
    ($total) = $resp =~ /TotalItemsInView="(\d+)"/;
    push @msgs, $resp =~ /<t:Message>(.*?)<\/t:Message>/gs;
    last if $resp =~ /IncludesLastItemInRange="true"/;
}
$total ||= scalar @msgs;

my $me    = norm($c{name});
my ($first, $last) = (split(' ', $me), '', '');
my $email = norm($c{user});
# "Ajanda:" komutu gönderebilecek adresler: kendi adresiniz + mail.conf ajanda_gonderenler
my %ajanda_from = map { (norm($_) =~ s/^\s+|\s+$//gr) => 1 } grep { /\S/ } ($c{user}, split /;/, ($c{ajanda_gonderenler} // q{}));
my ($own_domain) = $email =~ /@(\S+)/;

# Öncelikli kişiler: "Ad Soyad" ya da "Ad @firma" (firma, mail adresinin alan adında aranır).
my @vips = map { my $raw = $_; my @t = split ' ', norm($raw);
                 { label => $raw, names => [grep { !/^@/ } @t], domain => do { my ($d) = map { substr($_, 1) } grep { /^@/ } @t; $d } } }
           grep { /\S/ } map { s/^\s+|\s+$//gr } split /;/, ($c{oncelikli} // '');
sub words { grep { /\S/ } map { norm($_) =~ s/^\s+|\s+$//gr } split /;/, (shift // '') }
my @complaint_words = words($c{sikayet_kelimeleri});
my @payment_words   = words($c{odeme_kelimeleri});
my @dispute_words   = words($c{tartisma_kelimeleri});
my @guide_words     = words($c{rehber_kelimeleri});
my @guide_negative  = words($c{rehber_olumsuz});

sub vip_hits {
    my @people = @_;    # "Ad <adres>" ya da sadece ad/adres
    my %hit;
    for my $v (@vips) {
        for my $p (map { norm($_) } @people) {
            next if grep { $p !~ /\b\Q$_\E\b/ } @{ $v->{names} };
            next if $v->{domain} && $p !~ /@[a-z0-9.]*\Q$v->{domain}\E/;
            $hit{$v->{label}} = 1;
        }
    }
    return sort keys %hit;
}
sub hits { my ($text, @w) = @_; grep { $text =~ /\b\Q$_\E/ } @w }

my (%sect, %others, %seen, %dupes, %threads, @need_body, @ajanda, @ajanda_miss);
for my $m (@msgs) {
    my ($fromxml) = $m =~ /<t:From>(.*?)<\/t:From>/s;
    my $fname = $fromxml ? tag($fromxml, 'Name') : '';
    my $faddr = $fromxml ? tag($fromxml, 'EmailAddress') : '';
    {
        my $s = tag($m, 'Subject');
        # Kabul edilen konu başları: "Ajanda", "Ajanda Ekle", "EA", "EA Ekle" (iki nokta / tire isteğe bağlı)
        if ($s =~ /^\s*(?:(?:re|fw|fwd|ynt|ilt|ilet)\s*:\s*)*(?:ajanda|ea)(?:\s+ekle)?\s*(?:[:\-]|\s|$)/i && $ajanda_from{norm($faddr)}) {
            my ($aid) = $m =~ /<t:ItemId Id="([^"]+)"/;
            push @ajanda, { id => unxml($aid // q{}), subj => $s, from => $faddr, when => tag($m, 'DateTimeReceived'),
                prev => tag($m, 'Preview') };
            next;
        }
        # Teşhis: "ajanda" geçen ama konu formatı ya da gönderen uymayan mailler
        if (norm($s . ' ' . tag($m, 'Preview')) =~ /\bajanda/) {
            push @ajanda_miss, { subj => $s, from => $faddr, when => tag($m, 'DateTimeReceived'), prev => tag($m, 'Preview') };
        }
        next if $ajanda_only;
    }
    next if norm($faddr) eq $email;    # kendi gönderdiklerim
    my ($id) = $m =~ /<t:ItemId Id="([^"]+)"/;
    $id = unxml($id // '');
    my $to   = tag($m, 'DisplayTo');
    my $cc   = tag($m, 'DisplayCc');
    my $subj = tag($m, 'Subject');
    my $prev = tag($m, 'Preview');
    my $imp  = tag($m, 'Importance');
    my $when = tag($m, 'DateTimeReceived');
    $prev =~ s/\s+/ /g;
    my $rcpt = norm("$to $cc");
    # Alıcılarda aynı ilk ada sahip başka biri varsa (aynı ilk ada sahip başka bir çalışan) içerikteki hitap ona ait olabilir.
    my $other_same_first = $first && $rcpt =~ /\b\Q$first\E (?!\Q$last\E\b)[a-z]/;

    my @why = grep { defined } (
        ($me && norm($to) =~ /\Q$me\E/ ? 'Kime: size' : undef),
        ($me && norm($cc) =~ /\Q$me\E/ ? 'CC: size' : undef),
        ($first && !$other_same_first && norm($prev) =~ /\b\Q$first\E (bey|b\b|beyin|beye)/
            ? "içerikte '" . ucfirst($first) . " bey' geçiyor" : undef),
    );
    # Önizlemedeki alıntı başlıklarından ("From: Ad <adres>") yazışmadaki diğer kişiler.
    my @quoted = $prev =~ /([^:;<>'"]{2,60}?\s*<[^<>\s]+@[^<>\s]+>)/g;
    my @vip  = vip_hits("$fname <$faddr>", split(/;/, "$to;$cc"), @quoted);
    my $ntext = norm("$subj $prev");
    my @comp = hits($ntext, @complaint_words);
    push @comp, 'rehber şikâyeti' if hits($ntext, @guide_words) && hits($ntext, @guide_negative);
    my @pay  = hits($ntext, @payment_words);
    my @disp = hits($ntext, @dispute_words);

    my $section = @comp ? 'sikayet' : @pay ? 'odeme' : @vip ? 'vip' : @why ? 'mine' : @disp ? 'ortak' : undef;
    unless ($section) {
        $others{$to || '(boş)'}++;
        push @{ $threads{thread_key($subj)} }, { id => $id, from => $fname, faddr => $faddr, when => $when,
            subj => $subj, to => $to, prev => $prev } if thread_key($subj) ne '';
        next;
    }
    push @why, 'öncelikli kişi: ' . join(', ', @vip) if @vip;
    push @why, 'şikâyet: ' . join(', ', @comp) if @comp;
    push @why, 'ödeme / giriş riski: ' . join(', ', @pay) if @pay;
    push @why, 'tartışma işareti: ' . join(', ', @disp) if @disp;

    my $key = norm("$faddr|$subj|" . substr($prev, 0, 120));
    if (exists $seen{$key}) { $dupes{$seen{$key}}++; next }
    $seen{$key} = "$section:" . scalar @{ $sect{$section} //= [] };
    push @need_body, $id if $id && $section =~ /^(sikayet|odeme|ortak)$/;
    push @{ $sect{$section} }, { id => $id, text => join "\n",
        'Tarih: ' . local_time($when),
        "Kimden: $fname <$faddr>",
        "Kime: $to",
        ($cc ne '' ? "CC: $cc" : ()),
        "Konu: $subj",
        'Durum: ' . (tag($m, 'IsRead') eq 'true' ? 'okunmuş' : 'OKUNMAMIŞ')
            . (tag($m, 'HasAttachments') eq 'true' ? ', ekli' : '')
            . ($imp && $imp ne 'Normal' ? ", önem: $imp" : ''),
        'Neden listede: ' . join('; ', @why),
        "Önizleme: $prev" };
}

# Grup adreslerinde uzayan yazışmalar: en az 5 mesaj ve en az 3 farklı gönderen.
my @busy;
for my $k (keys %threads) {
    my @t = @{ $threads{$k} };
    my %senders = map { norm($_->{faddr}) => 1 } @t;
    my $external = grep { $_ !~ /\Q$own_domain\E$/ } keys %senders;
    next unless @t >= 5 && keys(%senders) >= 3;
    push @busy, { msgs => \@t, senders => [map { $_->{from} } @t], external => $external };
}
@busy = (sort { @{ $b->{msgs} } <=> @{ $a->{msgs} } } @busy)[0 .. 7];
@busy = grep { defined } @busy;
push @need_body, map { $_->{msgs}[0]{id} } @busy;    # zincirdeki en yeni mail

unshift @need_body, map { $_->{id} } @ajanda;
my %body = fetch_bodies(grep { $_ } @need_body[0 .. ($#need_body < 79 ? $#need_body : 79)]);
sub body_text {
    my $b = $body{ shift() // '' } // return ();
    $b =~ s/This message classified as\s*\w+//gi;
    $b =~ s/\s+/ /g;
    $b = substr($b, 0, 1800) . ' …[devamı mailde]' if length $b > 1800;
    return "Mail metni: $b";
}

print "=== Gelen Kutusu ($c{user}): son $c{hours} saatte $total mail, "
    . scalar(@msgs) . " tanesi tarandı ===\n";
print "\n##### AJANDA KOMUTLARI (konusu \"Ajanda:\" ile başlayan, izinli adreslerden): " . scalar(@ajanda) . " mail #####\n";
for my $a (@ajanda) {
    (my $key = $a->{id}) =~ s/[^A-Za-z0-9]//g;
    print "\n--- AJANDA ---\n",
        "Mail kimliği (kayıt anahtarı): m-" . substr($key, -40) . "\n",
        "Geliş: " . local_time($a->{when}) . "\n",
        "Kimden: $a->{from}\n",
        "Konu: $a->{subj}\n";
    my ($bt) = body_text($a->{id});
    print $bt ? "$bt\n" : "Önizleme: $a->{prev}\n";
}
if (@ajanda_miss) {
    print "\n##### İÇİNDE \"AJANDA\" GEÇEN AMA KOMUT SAYILMAYAN MAİLLER (konu formatı ya da gönderen uymuyor): "
        . scalar(@ajanda_miss) . " #####\n";
    for my $a (@ajanda_miss) {
        (my $p = $a->{prev}) =~ s/\s+/ /g;
        print '- ' . local_time($a->{when}) . " | $a->{from} | Konu: $a->{subj} | " . substr($p, 0, 160) . "\n";
    }
}
exit 0 if $ajanda_only;
my $i = 0;
for (['sikayet', 'ŞİKÂYET ŞÜPHESİ (rehber şikâyetleri dahil, tüm gelen kutusu)'],
     ['odeme',   'ÖDEME TALEBİ / ÖDEME YAPILMAZSA GİRİŞ RİSKİ (tüm gelen kutusu)'],
     ['vip',     'ÖNCELİKLİ KİŞİLER (tüm gelen kutusu)'],
     ['mine',    'SİZE DOĞRUDAN İLGİLİ'],
     ['ortak',   'ORTAK MAİLLERDE TARTIŞMA İŞARETİ (grup adresleri)']) {
    my ($s, $title) = @$_;
    my $list = $sect{$s} // [];
    print "\n##### $title: " . scalar(@$list) . " mail #####\n";
    for my $k (0 .. $#$list) {
        my $e = $list->[$k];
        print "\n--- [" . ++$i . "] ---\n$e->{text}\n";
        print "$_\n" for body_text($e->{id});
        print 'Aç: ' . owa_link($e->{id}) . "\n" if $e->{id};
        print "(Aynı mail $dupes{\"$s:$k\"} kez daha geldi)\n" if $dupes{"$s:$k"};
    }
}

print "\n##### ORTAK MAİLLERDE UZAYAN YAZIŞMALAR (5+ mesaj, 3+ kişi): " . scalar(@busy) . " zincir #####\n";
for my $t (@busy) {
    my @m = @{ $t->{msgs} };
    my %u; my @who = grep { !$u{$_}++ } @{ $t->{senders} };
    my $latest = $m[0];
    print "\n--- [" . ++$i . "] ---\n",
        "Konu: $latest->{subj}\n",
        'Mesaj sayısı: ' . scalar(@m) . ' (' . local_time($m[-1]{when}) . ' → ' . local_time($latest->{when}) . ")\n",
        'Katılanlar: ' . join(', ', @who[0 .. ($#who < 7 ? $#who : 7)]) . ($t->{external} ? '' : ' (sadece şirket içi)') . "\n",
        "Kime: $latest->{to}\n",
        "Son mesaj ($latest->{from}): $latest->{prev}\n";
    print "$_\n" for body_text($latest->{id});
    print 'Aç: ' . owa_link($latest->{id}) . "\n" if $latest->{id};
}

my $others_total = 0; $others_total += $_ for values %others;
print "\n##### DİĞERLERİ (grup adresleri vb.): $others_total mail, alıcıya göre sayı #####\n";
my @top = sort { $others{$b} <=> $others{$a} } keys %others;
printf "%4d  %s\n", $others{$_}, $_ for @top[0 .. ($#top < 24 ? $#top : 24)];
