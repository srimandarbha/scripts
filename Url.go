package main

import (
    "encoding/json"
    "fmt"
    "io/ioutil"
    "net/http"
    "os"
)

// Define the struct for the JSON response
type Item struct {
    AppOwner         string `json:"app.owner"`
    LastTransactionDate string `json:"last.transaction.date"`
    OwnerSystemID    string `json:"owner.system.id"`
    SystemIBMType    string `json:"system.ibm.machine.type"`
    SystemID         string `json:"system.id"`
    SystemPartitionID string `json:"system.partition.id"`
    SystemSerial     string `json:"system.serial"`
}

type Response struct {
    Items  []Item `json:"items"`
    Status struct {
        Code    int    `json:"code"`
        Message string `json:"message"`
    } `json:"status"`
}

func main() {
    // Define the endpoint URL
    url := "https://your-endpoint-url.com/api"

    // Create a new request
    req, err := http.NewRequest("GET", url, nil)
    if err != nil {
        fmt.Println(err)
        return
    }

    // Add the required headers
    req.Header.Set("Authorization", "Bearer YOUR_AUTH_TOKEN")
    req.Header.Set("Content-Type", "application/json")
    req.Header.Set("Accept", "application/json")

    // Create a new HTTP client and perform the request
    client := &http.Client{}
    resp, err := client.Do(req)
    if err != nil {
        fmt.Println(err)
        return
    }
    defer resp.Body.Close()

    // Check if the request was successful
    if resp.StatusCode != http.StatusOK {
        fmt.Println("Error: ", resp.Status)
        return
    }

    // Read the response body
    body, err := ioutil.ReadAll(resp.Body)
    if err != nil {
        fmt.Println(err)
        return
    }

    // Unmarshal the JSON data into the Response struct
    var response Response
    err = json.Unmarshal(body, &response)
    if err != nil {
        fmt.Println(err)
        return
    }

    // Print the extracted items
    for _, item := range response.Items {
        fmt.Println(item)
    }
}
