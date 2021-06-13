from exchangelib import Credentials, Account, Configuration, DELEGATE

mail_queue_list = []

credentials = Credentials(username='sdarbha@example.com', password='askmeidontknow')
config = Configuration(server='outlook.office365.com',credentials=credentials)
account = Account(primary_smtp_address='sdarbha@example.com', autodiscover=False, config = config, access_type=DELEGATE)

# filter to search subject/body or a word contained 
# https://github.com/ecederstrand/exchangelib/issues/83
unread_list = account.inbox.filter(is_read=False and "subject in 'BNAUTO:'")

if unread_list.count() > 0:
    for mail in unread_list:
        mail_queue_list.append({mail.subject : mail.body})
        #To mark a email as read
        mail.is_read=True
        mail.save()

print(mail_queue_list)
#soup.select('td div table tbody tr td div')[1].text
#soup.select('p strong')[0].text
#m=soup.select('div div table tbody td div')[5] 
#m.find('strong',text='Assigned To: ').next_sibling
