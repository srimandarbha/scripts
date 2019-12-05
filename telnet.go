package main

/*
Author: Sriman Darbha
*/

import (
	"bufio"
	"encoding/csv"
	"fmt"
	"net"
	"os"
	"regexp"
	"time"
)

const usage_output = `Usage: 
                 gocurl <url> <port>
                     or
                 gocurl <csv file>`

func file_exists(filename string) bool {
	file_info, err := os.Stat(filename)
	if os.IsNotExist(err) {
		return false
	}
	return !file_info.IsDir()
}

func check_port(hostname string, port string) {
	conn, err := net.DialTimeout("tcp", net.JoinHostPort(hostname, port), time.Second*3)
	if err != nil {
		fmt.Println(err)
		return
	}
	defer conn.Close()
	fmt.Println("port open:", net.JoinHostPort(hostname, port))
}

func main() {
	hnames := []string{}
	switch len(os.Args) {
	case 1:
		fmt.Println(usage_output)
		os.Exit(1)
	case 2:
		matched, _ := regexp.MatchString("[a-z0-9]+.(csv|txt|ini)", os.Args[1])
		if matched == true {
			if file_exists(os.Args[1]) {
				data, _ := os.Open(os.Args[1])
				csv_content := csv.NewReader(bufio.NewReader(data))
				for {
					record, err := csv_content.Read()
					if err != nil {
						break
					}
					fmt.Println(record)
					/* you are working here */
				}
			}
		}
	case 3:
		check_port(string(os.Args[1]), string(os.Args[2]))
	default:
		fmt.Println(usage_output)
		os.Exit(1)
	}

	for _, name := range hnames {
		dname, _ := net.LookupIP(name)
		for _, hname := range dname {
			fmt.Println(name, hname)
		}
	}

}
