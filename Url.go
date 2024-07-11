package main

import (
	"encoding/json"
	"fmt"
	"io/ioutil"
	"log"
	"net/http"
	"os"
	"sync"
	"time"
)

// Define structures as per your image
type EndpointDetail struct {
	GUID                  string            `json:"guid"`
	ProductID             string            `json:"ProductId"`
	AppOwner              string            `json:"app.owner"`
	CallhomeStatus        string            `json:"callhome.status"`
	HealthStatus          string            `json:"health-status"`
	LastTranscDate        string            `json:"last.transaction.date"`
	OwnerSystemID         string            `json:"ownersystemid"`
	Status                map[string]int    `json:"status"`
	SystemIbmMachineType  string            `json:"system.ibm.machine.type"`
	SystemID              string            `json:"system.id"`
	SystemModel           string            `json:"system.model"`
	SystemPartitionID     string            `json:"system.partition.id"`
	SystemSerial          string            `json:"system.serial"`
	Version               string            `json:"version"`
}

type Item struct {
	AppOwner            string `json:"app.owner"`
	LastTransactionDate string `json:"last.transaction.date"`
	OwnerSystemID       string `json:"owner.system.id"`
	SystemID            string `json:"system.id"`
	SystemIBmType       string `json:"system.ibm.machine.type"`
	SystemPartitionID   string `json:"system.partition.id"`
	SystemSerial        string `json:"system.serial"`
}

type Response struct {
	Items  []Item `json:"items"`
	Status struct {
		Code    int    `json:"code"`
		Message string `json:"message"`
	} `json:"status"`
}

func GetError(err error, msg string) {
	if err != nil {
		fmt.Println(msg, err)
		return
	}
}

type EsaInstance struct {
	HardwareURL string `json:"hardwareurl"`
	DeviceURL   string `json:"deviceurl"`
	Token       string `json:"token"`
}

type EsaInstances struct {
	Instances map[string]EsaInstance `json:"esa_instances"`
}

func main() {
	// Load configuration from config.json
	configFile := "config.json"
	file, err := os.Open(configFile)
	if err != nil {
		log.Fatalf("Error opening config file: %v", err)
	}
	defer file.Close()

	byteValue, err := ioutil.ReadAll(file)
	if err != nil {
		log.Fatalf("Error reading config file: %v", err)
	}

	var esaInstances EsaInstances
	err = json.Unmarshal(byteValue, &esaInstances)
	if err != nil {
		log.Fatalf("Error unmarshalling config file: %v", err)
	}

	// Create channels for goroutines
	hardwareChan := make(chan Response)
	systemDetailChan := make(chan EndpointDetail)
	var wg sync.WaitGroup

	for _, instance := range esaInstances.Instances {
		wg.Add(1)
		go func(instance EsaInstance) {
			defer wg.Done()
			hardwareURL := instance.HardwareURL

			// Fetch hardware details
			resp, err := makeRequest(hardwareURL, instance.Token)
			GetError(err, "Error fetching hardware details:")
			defer resp.Body.Close()

			body, err := ioutil.ReadAll(resp.Body)
			GetError(err, "Error reading response body:")

			var hardwareResponse Response
			err = json.Unmarshal(body, &hardwareResponse)
			GetError(err, "Error unmarshalling hardware response:")

			hardwareChan <- hardwareResponse
		}(instance)
	}

	// Process hardware details and fetch system detail
	go func() {
		for hardwareResponse := range hardwareChan {
			for _, system := range hardwareResponse.Items {
				wg.Add(1)
				go func(systemID string, instance EsaInstance) {
					defer wg.Done()
					systemDetailURL := fmt.Sprintf("%s/%s", instance.DeviceURL, systemID)
					resp, err := makeRequest(systemDetailURL, instance.Token)
					GetError(err, "Error fetching system detail for ID "+systemID+":")
					defer resp.Body.Close()

					body, err := ioutil.ReadAll(resp.Body)
					GetError(err, "Error reading response body:")

					var systemDetail EndpointDetail
					err = json.Unmarshal(body, &systemDetail)
					GetError(err, "Error unmarshalling system detail:")

					systemDetailChan <- systemDetail
				}(system.SystemID, instance)
			}
		}
	}()

	// Collect results and wait for completion
	go func() {
		for systemDetail := range systemDetailChan {
			fmt.Printf("System ID: %s, Product ID: %s, App Owner: %s\n", systemDetail.SystemID, systemDetail.ProductID, systemDetail.AppOwner)
		}
	}()

	wg.Wait()
	close(systemDetailChan)
}

func makeRequest(url, jwtToken string) (*http.Response, error) {
	client := &http.Client{Timeout: 10 * time.Second}
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", fmt.Sprintf("Bearer %s", jwtToken))

	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("unexpected status code: %d", resp.StatusCode)
	}

	return resp, nil
}
