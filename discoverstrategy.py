import requests
from requests.auth import HTTPDigestAuth

import os.path 

from collections import deque
from lxml import html
from urllib.parse import urlparse, urljoin

from customauth import get_auth_info
from fuzzerstrategy import FuzzerStrategy
from helpers import get_url_params, trim_url_params, validate_url

class DiscoverStrategy(FuzzerStrategy):
    #initialize everything necessary here
    def __init__(self, args):
        super(DiscoverStrategy, self).__init__()

        self.login_action = ''
        self.login_discovered = False

        self.common_words_urls = []

        self.auth_tuple = ()

        self.source_url = args[0] #The first url to be requested

        #A Queue to be used to decide which order to visit pages for crawling
        self.urlqueue = deque()
        self.urlqueue.append(self.source_url)

        self.discovered_urls = {self.source_url}

        #stores all data discovered at each visited url
        self.url_data = dict()

        #Parse the command line arguments passed into the constructor
        for arg in args[1:]:
            arg_value_pair = arg.split('=')
            argname  = arg_value_pair[0]
            argvalue = arg_value_pair[1]

            if argname == '--custom-auth':
                self.auth_tuple = get_auth_info(argvalue)
            elif argname == '--common-words':
                self._parse_common_words(argvalue)

    #Executes the fuzzing algorithm
    def execute(self):
        #Begin code for any necessary logging in.
        #This only needs to be executed once.
        session = requests.session()

        response = session.get(self.source_url)
        parsed_body = html.fromstring(response.content)

        if self._contains_login_form(parsed_body):
            self.login_action = self._get_login_forms(parsed_body)[0].action
            self.login_discovered = True
            self._login(session)

        while len(self.urlqueue):
            if self.login_discovered:
                self._login(session)

            url = self.urlqueue.popleft()
            print("Currently Visiting: %s" % (url))

            just_logged_in = False

            response = session.get(url)
            parsed_body = html.fromstring(response.content)

            if self._contains_login_form(parsed_body) and not self.login_discovered:
                self.login_action = self._get_login_forms(parsed_body)[0].action
                self.login_discovered = True
                self._login(session)
                just_logged_in = True

            if just_logged_in:
                response = session.get(url)
                parsed_body = html.fromstring(response.content)

            #get the title for the requested page and store it
            self.url_data[url] = dict()

            #response time in milliseconds
            self.url_data[url]['response_time'] =\
                response.elapsed.total_seconds() * 1000
            #status of the response
            self.url_data[url]['status_code'] = response.status_code

            titles = parsed_body.xpath("//title/text()")
            self.url_data[url]['title'] = titles[0] if len(titles) else url
          
            all_inputs = parsed_body.xpath("//input")
            self.url_data[url]['forminput'] =\
                all_inputs if len(all_inputs) else []

            #store any cookies this page might have
            self.url_data[url]['cookies'] = response.cookies

            self._discover_page_link_data(url, parsed_body)

    #simply outputs the contents of the data structure
    def output_discovered_data(self):
        print("\n\n")

        for (url) in self.url_data:
            print(self.url_data[url]['title'])

            print((" " * 4) + "Form Inputs:")
            if len(self.url_data[url]['forminput']) > 0:
                for input_elem in self.url_data[url]['forminput']:
                    print((" " * 8) + str(input_elem))
            else:
                print((" " * 8) + "None")

            print((" " * 4) + "URL Parameters:")
            if len(self.url_data[url]['urlparams']) > 0:
                for urlparam in self.url_data[url]['urlparams']:
                    print((" " * 8) + urlparam)
            else:
                print((" " * 8) + "None")

            print((" " * 4) + "Cookies:")
            if len(self.url_data[url]['cookies']) > 0:
                for cookie in self.url_data[url]['cookies']:
                    print((" " * 8) + str(cookie))
            else:
                print((" " * 8) + "None")

            print((" " * 4) + "Links:")
            if len(self.url_data[url]['accessible_links']) > 0:
                for link in self.url_data[url]['accessible_links']:
                    print((" " * 8) + link)
            else:
                print((" " * 8) + "None")


    #Parses the text file given for common words
    #Still needs implementation
    def _parse_common_words(self, word_file):
        if os.path.isfile(word_file):
            print("Parsing common words file: %s" % (word_file))

            for line in open(word_file):
                stripped_line = line.strip()

                self.common_words_urls.append(
                    self._generate_absolute_link(stripped_line)
                )
                self.common_words_urls.append(
                    self._generate_absolute_link(stripped_line + '.jsp')
                )
                self.common_words_urls.append(
                    self._generate_absolute_link(stripped_line + '.php')
                )
        else:
            raise Exception("%s: file not found" % (word_file))

    #Discovers the links infomration on a page
    def _discover_page_link_data(self, url, html_body):
        #Prepare to store any url parameters present in links on the page
        self.url_data[url]['urlparams'] = set()
        #We're also storing unique links acessible from the given page
        self.url_data[url]['accessible_links'] = set()
        all_links = set(
            filter(
                lambda url: validate_url(url, self.source_url),
                html_body.xpath("//a/@href")
            )
        )

        for link in all_links:
            absolute_link = self._generate_absolute_link(link)

            #we want our accessible links to be links without url parameters
            self.url_data[url]['accessible_links'].add(
                absolute_link
            )

            #get the url parameters from the url and store them in the data
            #structure
            urlparams = get_url_params(absolute_link)
            self.url_data[url]['urlparams'].update(
                urlparams
            )

        all_links = set(
            map(
                lambda url: trim_url_params(self._generate_absolute_link(url)),
                all_links
            )
        )
        for link in (all_links - self.discovered_urls):
            self.discovered_urls.add(link)
            self.urlqueue.append(link)

    #Conducts the requests necessary to 'login'
    def _login(self, session):
        #perform authentication here
        if self.auth_tuple != ():
            #Generate the login url
            login_url = self._generate_absolute_link(self.login_action)

            #Create the data payload used to log the user in            
            login_data = dict(
                username=self.auth_tuple[0],
                password=self.auth_tuple[1],
                Login='Login'
            )

            #Perform the login
            login_response = session.post(login_url, data=login_data)

    #Gets any login forms present on an html page
    def _get_login_forms(self, html_body):
        return html_body.xpath("//form[descendant::input[@name='Login']]")

    #Tests if a page contains any login forms
    def _contains_login_form(self, html_body):
        login_forms = html_body.xpath("//form[descendant::input[@name='Login']]")

        return len(login_forms) >= 1

    def _generate_absolute_link(self, url):
        #We want to create a link as an absolute url so we don't get
        #errors with our requests
        absolute_link = ''
        if self.source_url.endswith('/'):
            absolute_link = urljoin(self.source_url, url)
        else:
           absolute_link = urljoin(self.source_url + '/', url)

        return absolute_link