using Azure.AI.Projects;
using Azure.Identity;
using Microsoft.Agents.AI;

const string projectEndpoint = "https://rg-openai-hub.services.ai.azure.com/api/projects/rg-openai-hub-model-router";
const string agentName = "agentmeridian";

// Connect to Azure AI Foundry using AIProjectClient (supports Foundry IQ / Responses API agents)
// Make sure to run `az login` first for authentication
var projectClient = new AIProjectClient(
    endpoint: new Uri(projectEndpoint),
    tokenProvider: new DefaultAzureCredential());

// Retrieve the Foundry IQ agent by name and wrap as a MAF AIAgent
AIAgent agent = await projectClient.GetAIAgentAsync(agentName);
Console.WriteLine($"Agent '{agentName}' retrieved successfully.");

// Start a new conversation session
AgentSession session = await agent.CreateSessionAsync();

// Run the agent and display the response
AgentResponse response = await agent.RunAsync("process articles", session);
Console.WriteLine(response);
