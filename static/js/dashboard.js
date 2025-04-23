// Define the available sections
const sections = ['market', 'positions', 'history', 'logging', 'account', 'config'];

// Show the specified section and hide others
function showSection(sectionId) {
    console.log(`Switching to section: ${sectionId}`); // Debug logging
    
    // Hide all sections
    sections.forEach(section => {
        const element = document.getElementById(section);
        if (element) {
            element.classList.add('hidden');
            console.log(`Hidden section: ${section}`);
        } else {
            console.error(`Section element not found: ${section}`);
        }
        
        // Remove active class from nav items
        document.querySelectorAll(`[data-section="${section}"]`).forEach(el => {
            el.classList.remove('active');
        });
    });
    
    // Show the selected section
    const selectedSection = document.getElementById(sectionId);
    if (selectedSection) {
        selectedSection.classList.remove('hidden');
        console.log(`Showing section: ${sectionId}`);
        
        // Log to the system logger if it's available
        if (window.systemLogger && sectionId === 'logging') {
            window.systemLogger.logTradeIssue('Logging section opened', { timestamp: new Date().toISOString() });
        }
    } else {
        console.error(`Selected section not found in DOM: ${sectionId}`);
    }
    
    // Add active class to corresponding nav items
    document.querySelectorAll(`[data-section="${sectionId}"]`).forEach(el => {
        el.classList.add('active');
    });
    
    // Save the current section to localStorage
    localStorage.setItem('dashboard-active-section', sectionId);
}

// Restore the last active section on page load
document.addEventListener('DOMContentLoaded', () => {
    console.log('Dashboard initializing...'); // Debug logging
    
    // Check if all section elements are in the DOM
    sections.forEach(section => {
        const element = document.getElementById(section);
        console.log(`Section ${section} exists: ${!!element}`);
    });
    
    // For initial testing, force showing the logging section
    showSection('logging');
    
    // Add event listeners to navigation items
    document.querySelectorAll('[data-section]').forEach(navItem => {
        const sectionId = navItem.getAttribute('data-section');
        navItem.addEventListener('click', (e) => {
            e.preventDefault();
            console.log(`Navigation clicked: ${sectionId}`); // Debug logging
            showSection(sectionId);
        });
    });
    
    console.log('Dashboard initialized successfully');
});

// Export the showSection function to be used by other scripts
window.showSection = showSection;